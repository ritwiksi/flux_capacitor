"""One-dimensional PCM enthalpy conduction vs mixed sensible-water storage.

First milestone only. Controller is a deterministic daily top/bottom-eight-hours
heuristic, NOT a globally optimal cooling dispatch. Fluid boundary temperatures
are fixed at 37 C on charge and 27 C during regeneration, so this model cannot
claim actual cooling-system electricity/cost/emissions savings.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .materials import Material


@dataclass(frozen=True)
class Config:
    panels: int = 100
    area_per_panel_m2: float = 1.0
    thickness_m: float = 0.05
    supply_c: float = 27.0
    return_c: float = 37.0
    heat_transfer_w_m2_k: float = 150.0
    pcm_cells: int = 8
    timestep_s: float = 60.0
    peak_hours_daily: int = 8
    regen_hours_daily: int = 8
    # When True, heat released during regeneration is limited each hour to the headroom
    # under the month's no-storage peak (max IT power - this hour's IT power), so storage
    # cannot create a new cooling peak. This uses perfect foresight of the month's peak,
    # an idealization applied identically to water and PCM. False reproduces milestone 1.
    cap_regeneration: bool = True


def _state_to_temp(h: np.ndarray, material: Material):
    cp = material.heat_capacity_j_kg_k
    latent = material.latent_heat_j_kg
    low, high = material.melt_low_c, material.melt_high_c
    span = high - low
    solid_h, liquid_h = cp * low, cp * high + latent
    t = np.where(h <= solid_h, h / cp,
         np.where(h >= liquid_h, (h-latent)/cp,
                  (h + latent*low/span)/(cp+latent/span)))
    f = np.clip((t-low)/span, 0.0, 1.0)
    return t, f


def _mode_schedule(load: pd.DataFrame, cfg: Config) -> np.ndarray:
    """Daily peak/low workload scheduling; never tune to PCM properties."""
    if cfg.peak_hours_daily + cfg.regen_hours_daily > 24:
        raise ValueError("Daily charge and regeneration windows overlap.")
    mode = np.zeros(len(load), dtype=np.int8)
    for _, day in load.groupby(load.timestamp.dt.floor("D"), sort=True):
        if len(day) != 24:
            raise ValueError("Expected complete UTC days.")
        ranked = day.sort_values(["it_power_kw", "timestamp"], ascending=[True, True], kind="mergesort")
        mode[ranked.index[:cfg.regen_hours_daily]] = -1
        mode[ranked.index[-cfg.peak_hours_daily:]] = 1
    return mode


def simulate(workload: pd.DataFrame, material: Material, cfg: Config) -> pd.DataFrame:
    """Run both systems under an identical mode schedule and geometry.

    Positive storage_kw is heat absorption; negative is heat regeneration.
    `thermal_plant_kw` is only a heat-rejection proxy, NOT electrical power.
    """
    if cfg.panels < 1 or cfg.area_per_panel_m2 <= 0 or cfg.thickness_m <= 0:
        raise ValueError("Panel count, area and thickness must be positive.")
    if not cfg.supply_c < cfg.return_c or cfg.pcm_cells < 2:
        raise ValueError("Require supply < return and at least 2 PCM cells.")
    if cfg.timestep_s <= 0 or cfg.heat_transfer_w_m2_k <= 0:
        raise ValueError("Heat-transfer coefficient and timestep must be positive.")
    # Explicit FTCS conduction stability check using minimum sensible cp.
    dx = cfg.thickness_m / cfg.pcm_cells
    alpha = material.conductivity_w_m_k / (material.density_kg_m3 * material.heat_capacity_j_kg_k)
    dt_max = 0.40 * dx * dx / alpha
    actual_step = min(cfg.timestep_s, dt_max, 60.0)
    nstep = int(np.ceil(3600.0 / actual_step))
    dt = 3600.0 / nstep

    area = cfg.panels * cfg.area_per_panel_m2
    rho = material.density_kg_m3
    mass_cell = rho * area * dx
    cp = material.heat_capacity_j_kg_k
    h_pcm = np.full(cfg.pcm_cells, cp * cfg.supply_c, dtype=float)
    t_water = cfg.supply_c
    c_water = 1000.0 * area * cfg.thickness_m * 4180.0
    u = cfg.heat_transfer_w_m2_k
    modes = _mode_schedule(workload.reset_index(drop=True), cfg)
    month_peak_kw = float(workload.it_power_kw.max())
    rows = []
    for i, (ts, q_it) in enumerate(zip(workload.timestamp, workload.it_power_kw)):
        mode = int(modes[i])
        # Maximum heat (W) either system may release into the plant this hour.
        regen_cap_w = max(0.0, month_peak_kw - float(q_it)) * 1000.0 if cfg.cap_regeneration else float("inf")
        fluid_temp = cfg.return_c if mode == 1 else cfg.supply_c
        energy_pcm_j = 0.0
        energy_water_j = 0.0
        # Disabled mode means physically bypassed and insulated.
        if mode:
            for _ in range(nstep):
                temps, _ = _state_to_temp(h_pcm, material)
                # Conductance includes half-cell resistance at module wall.
                ua_pcm = area / (1.0/u + dx/(2*material.conductivity_w_m_k))
                q_surface = ua_pcm * (fluid_temp - temps[0])
                # A low-IT-power facility cannot provide more heat than it produces.
                if mode == 1:
                    q_surface = max(0.0, min(q_surface, float(q_it)*1000))
                else:
                    q_surface = max(min(0.0, q_surface), -regen_cap_w)
                q_internal = material.conductivity_w_m_k * area/dx * (temps[:-1]-temps[1:])
                net = np.zeros(cfg.pcm_cells)
                net[0] += q_surface
                net[:-1] -= q_internal
                net[1:] += q_internal
                h_pcm += net * dt / mass_cell
                energy_pcm_j += q_surface*dt

                q_water = u*area*(fluid_temp - t_water)
                if mode == 1:
                    q_water = max(0.0, min(q_water, float(q_it)*1000))
                else:
                    q_water = max(min(0.0, q_water), -regen_cap_w)
                t_water += q_water*dt/c_water
                energy_water_j += q_water*dt
        t, fraction = _state_to_temp(h_pcm, material)
        pcm_kw = energy_pcm_j / 3_600_000.0
        water_kw = energy_water_j / 3_600_000.0
        rows.append(dict(
            timestamp=ts, it_power_kw=float(q_it), mode=mode,
            pcm_storage_kw=pcm_kw, water_storage_kw=water_kw,
            pcm_melt_fraction=float(np.mean(fraction)),
            pcm_mean_c=float(np.mean(t)), water_mean_c=float(t_water),
            pcm_plant_thermal_kw=float(q_it)-pcm_kw,
            water_plant_thermal_kw=float(q_it)-water_kw,
        ))
    return pd.DataFrame(rows)


def summarize(result: pd.DataFrame) -> dict:
    return {
        "it_peak_kw": float(result.it_power_kw.max()),
        "pcm_heat_absorbed_kwh": float(result.pcm_storage_kw.clip(lower=0).sum()),
        "pcm_heat_regenerated_kwh": float(-result.pcm_storage_kw.clip(upper=0).sum()),
        "water_heat_absorbed_kwh": float(result.water_storage_kw.clip(lower=0).sum()),
        "water_heat_regenerated_kwh": float(-result.water_storage_kw.clip(upper=0).sum()),
        "pcm_max_melt_percent": float(100*result.pcm_melt_fraction.max()),
        "pcm_peak_thermal_shave_kw": float((result.it_power_kw.max() - result.pcm_plant_thermal_kw.max())),
        "water_peak_thermal_shave_kw": float((result.it_power_kw.max() - result.water_plant_thermal_kw.max())),
    }
