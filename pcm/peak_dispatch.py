"""Threshold peak-shaving dispatch for the existing PCM and water thermal models.

Every target is a THERMAL plant-load ceiling (not electric kW). The controller
absorbs heat when IT load exceeds the ceiling and regenerates only with spare
headroom beneath it. PCM and water each get their own lowest feasible ceiling.
This is a deterministic, month-ahead perfect-foresight benchmark, NOT a
predictive real-time controller or an electricity-cost optimization.

Initial conditions match the original model: both stores start at 27 C.
Residual heat at the end of the month is disclosed; cyclic steady state is
not proven, so extrapolating one month's shave to chiller sizing is speculative.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log2

import numpy as np
import pandas as pd

from .materials import Material
from .thermal import Config, _state_to_temp


@dataclass(frozen=True)
class PeakSearch:
    pcm_target_kw: float
    water_target_kw: float
    tolerance_kw: float
    search_iterations: int
    pcm_end_stored_kwh: float
    water_end_stored_kwh: float


def _simulate_targets(
    workload: pd.DataFrame,
    material: Material,
    cfg: Config,
    pcm_target_kw: float,
    water_target_kw: float,
    *,
    early_exit: bool = False,
) -> tuple[pd.DataFrame | None, bool, bool]:
    """Simulate two independent, threshold-constrained heat stores.

    During search, stop simulating a store as soon as it misses its target.
    Both stores use the identical 27/37 C boundary conditions and geometry.
    """
    if cfg.panels < 1 or cfg.area_per_panel_m2 <= 0 or cfg.thickness_m <= 0:
        raise ValueError("Panel count, area and thickness must be positive.")
    if cfg.supply_c >= cfg.return_c or cfg.pcm_cells < 2:
        raise ValueError("Require supply < return and at least 2 PCM cells.")
    if cfg.timestep_s <= 0 or cfg.heat_transfer_w_m2_k <= 0:
        raise ValueError("Heat-transfer coefficient and timestep must be positive.")
    if material.conductivity_w_m_k <= 0 or material.heat_capacity_j_kg_k <= 0 or material.density_kg_m3 <= 0:
        raise ValueError("Material transport and thermal properties must be positive.")
    if not np.isfinite([pcm_target_kw, water_target_kw]).all() or min(pcm_target_kw, water_target_kw) < 0:
        raise ValueError("Peak targets must be finite, nonnegative thermal kW.")
    if workload.empty or not np.isfinite(workload.it_power_kw.to_numpy(float)).all() or (workload.it_power_kw < 0).any():
        raise ValueError("Workload must contain finite, nonnegative IT loads.")

    dx = cfg.thickness_m / cfg.pcm_cells
    area = cfg.panels * cfg.area_per_panel_m2
    mass_cell = material.density_kg_m3 * area * dx
    alpha = material.conductivity_w_m_k / (material.density_kg_m3 * material.heat_capacity_j_kg_k)
    dt_max = 0.40 * dx * dx / alpha
    nstep = int(ceil(3600.0 / min(cfg.timestep_s, dt_max, 60.0)))
    dt = 3600.0 / nstep

    h_pcm = np.full(cfg.pcm_cells, material.heat_capacity_j_kg_k * cfg.supply_c, dtype=float)
    t_water = cfg.supply_c
    c_water = 1000.0 * area * cfg.thickness_m * 4180.0
    ua_pcm = area / (1.0 / cfg.heat_transfer_w_m2_k + dx / (2.0 * material.conductivity_w_m_k))
    conductance = material.conductivity_w_m_k * area / dx
    ua_water = cfg.heat_transfer_w_m2_k * area

    pcm_feasible = water_feasible = True
    rows = []
    for ts, q in zip(workload.timestamp, workload.it_power_kw):
        q = float(q)
        pmode = 1 if q > pcm_target_kw else -1 if q < pcm_target_kw else 0
        wmode = 1 if q > water_target_kw else -1 if q < water_target_kw else 0
        pcm_limit = abs(q - pcm_target_kw) * 1000.0
        water_limit = abs(q - water_target_kw) * 1000.0
        p_energy = w_energy = 0.0

        if pmode != 0 and pcm_feasible:
            fluid_temp = cfg.return_c if pmode == 1 else cfg.supply_c
            for _ in range(nstep):
                t, _ = _state_to_temp(h_pcm, material)
                q_face = ua_pcm * (fluid_temp - t[0])
                if pmode == 1:
                    q_face = max(0.0, min(q_face, pcm_limit, q * 1000.0))
                else:
                    q_face = min(0.0, max(q_face, -pcm_limit))
                q_internal = conductance * (t[:-1] - t[1:])
                # Conservative finite-volume conduction with one exposed face.
                h_pcm[0] += (q_face - q_internal[0]) * dt / mass_cell
                h_pcm[1:-1] += (q_internal[:-1] - q_internal[1:]) * dt / mass_cell
                h_pcm[-1] += q_internal[-1] * dt / mass_cell
                p_energy += q_face * dt

        if wmode != 0 and water_feasible:
            fluid_temp = cfg.return_c if wmode == 1 else cfg.supply_c
            for _ in range(nstep):
                q_water = ua_water * (fluid_temp - t_water)
                if wmode == 1:
                    q_water = max(0.0, min(q_water, water_limit, q * 1000.0))
                else:
                    q_water = min(0.0, max(q_water, -water_limit))
                t_water += q_water * dt / c_water
                w_energy += q_water * dt

        pcm_kw = p_energy / 3_600_000.0
        water_kw = w_energy / 3_600_000.0
        p_plant = q - pcm_kw
        w_plant = q - water_kw

        if pcm_feasible and p_plant > pcm_target_kw + 1e-7:
            pcm_feasible = False
        if water_feasible and w_plant > water_target_kw + 1e-7:
            water_feasible = False
        if early_exit:
            if not pcm_feasible and not water_feasible:
                break
            continue

        temps, fraction = _state_to_temp(h_pcm, material)
        rows.append(dict(
            timestamp=ts, it_power_kw=q, mode=pmode,
            pcm_mode=pmode, water_mode=wmode,
            pcm_storage_kw=pcm_kw, water_storage_kw=water_kw,
            pcm_melt_fraction=float(np.mean(fraction)),
            pcm_mean_c=float(np.mean(temps)), water_mean_c=float(t_water),
            pcm_plant_thermal_kw=p_plant, water_plant_thermal_kw=w_plant,
        ))

    return (None if early_exit else pd.DataFrame(rows)), pcm_feasible, water_feasible


def optimize_peak_dispatch(
    workload: pd.DataFrame,
    material: Material,
    cfg: Config,
    *,
    tolerance_kw: float = 0.25,
) -> tuple[pd.DataFrame, PeakSearch]:
    """Binary-search both stores' lowest feasible thermal-peak ceilings.

    A target is feasible only if actual hourly heat-rejection load never
    exceeds it. These are hourly average peaks, not transient minute peaks.
    The two independent searches share one simulation pass per iteration.
    """
    if tolerance_kw <= 0 or not np.isfinite(tolerance_kw):
        raise ValueError("Search tolerance must be finite and positive.")
    if workload.empty:
        raise ValueError("Workload cannot be empty.")
    no_storage_peak = float(workload.it_power_kw.max())
    if not np.isfinite(no_storage_peak) or no_storage_peak < 0:
        raise ValueError("Invalid no-storage peak.")

    p_lo = w_lo = 0.0
    p_hi = w_hi = no_storage_peak
    iterations = max(0, ceil(log2(max(no_storage_peak, tolerance_kw) / tolerance_kw)))
    # Search never assumes any improvement is possible: no storage is feasible.
    for _ in range(iterations):
        p_mid = (p_lo + p_hi) / 2.0
        w_mid = (w_lo + w_hi) / 2.0
        _, p_ok, w_ok = _simulate_targets(workload, material, cfg, p_mid, w_mid, early_exit=True)
        if p_ok:
            p_hi = p_mid
        else:
            p_lo = p_mid
        if w_ok:
            w_hi = w_mid
        else:
            w_lo = w_mid

    result, p_ok, w_ok = _simulate_targets(workload, material, cfg, p_hi, w_hi)
    if not p_ok or not w_ok or result is None:
        raise RuntimeError("Threshold search did not produce a feasible dispatch.")
    pcm_remaining = float(result.pcm_storage_kw.sum())
    water_remaining = float(result.water_storage_kw.sum())
    return result, PeakSearch(
        pcm_target_kw=p_hi,
        water_target_kw=w_hi,
        tolerance_kw=tolerance_kw,
        search_iterations=iterations,
        pcm_end_stored_kwh=max(0.0, pcm_remaining),
        water_end_stored_kwh=max(0.0, water_remaining),
    )
