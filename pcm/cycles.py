"""Conservative repeat-month audit of the idealized threshold controller.

A finite one-month trajectory is *not* evidence of repeatable plant downsizing.
Replay the exact same workload until the complete PCM enthalpy vector and
water temperature converge. Do not claim a cyclic result if they do not.
Replaying a month is itself an idealized periodic-boundary test, not a forecast.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

from .materials import Material
from .thermal import Config
from .peak_dispatch import PeakSearch, _simulate_targets


@dataclass(frozen=True)
class CycleAudit:
    passes: int
    pcm_verified: bool
    water_verified: bool
    pcm_state_drift_kwh: float
    water_state_drift_kwh: float
    pcm_energy_residual_kwh: float
    water_energy_residual_kwh: float
    tolerance_kwh: float
    note: str


def audit_cycles(
    workload: pd.DataFrame,
    material: Material,
    cfg: Config,
    targets: PeakSearch,
    *,
    max_passes: int = 4,
    tolerance_kwh: float = 0.2,
) -> tuple[pd.DataFrame, CycleAudit]:
    """Repeat a monthly dispatch and check terminal-state return.

    Each pass starts with the previous pass' full PCM enthalpy vector and
    mixed water temperature. Verification is system-specific, and requires
    both an enforced load ceiling and a converged internal state.
    """
    if max_passes < 2 or tolerance_kwh <= 0:
        raise ValueError("Need at least two passes and a positive convergence tolerance.")
    area = cfg.panels * cfg.area_per_panel_m2
    mass_cell = material.density_kg_m3 * area * cfg.thickness_m / cfg.pcm_cells
    capacity_water = 1000 * area * cfg.thickness_m * 4180.0
    pstate = np.full(cfg.pcm_cells, material.heat_capacity_j_kg_k * cfg.supply_c, dtype=float)
    wstate = float(cfg.supply_c)
    data = None
    p_ok = w_ok = False
    p_drift = w_drift = float("inf")
    p_balance = w_balance = float("inf")
    passes = 0
    for k in range(max_passes):
        old_p = pstate.copy()
        old_w = wstate
        end = {}
        data, p_ok, w_ok = _simulate_targets(
            workload, material, cfg, targets.pcm_target_kw, targets.water_target_kw,
            initial_pcm_h=old_p, initial_water_c=old_w, state_out=end,
        )
        assert data is not None
        pstate = end["pcm_h"]
        wstate = end["water_c"]
        # L1 drift catches opposing enthalpy changes that total-energy drift misses.
        p_drift = float(np.abs(pstate - old_p).sum() * mass_cell / 3_600_000.0)
        w_drift = abs(wstate - old_w) * capacity_water / 3_600_000.0
        # Compare integrated external flux against actual internal-energy change.
        p_balance = abs(float(data.pcm_storage_kw.sum()) - float((pstate - old_p).sum() * mass_cell / 3_600_000.0))
        w_balance = abs(float(data.water_storage_kw.sum()) - float((wstate - old_w) * capacity_water / 3_600_000.0))
        passes = k + 1
        if k >= 1 and p_drift <= tolerance_kwh and w_drift <= tolerance_kwh:
            break

    pcm_verified = bool(p_ok and p_drift <= tolerance_kwh and p_balance < 0.01)
    water_verified = bool(w_ok and w_drift <= tolerance_kwh and w_balance < 0.01)
    return data, CycleAudit(
        passes=passes, pcm_verified=pcm_verified, water_verified=water_verified,
        pcm_state_drift_kwh=p_drift, water_state_drift_kwh=w_drift,
        pcm_energy_residual_kwh=p_balance, water_energy_residual_kwh=w_balance,
        tolerance_kwh=tolerance_kwh,
        note=("Repeat-month convergence is a hypothetical periodic-boundary benchmark. "
              "It does not establish reliability with actual forecasts, seasonal weather, "
              "aging, plant bottlenecks, or physical temperature constraints at equipment."),
    )
