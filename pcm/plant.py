"""Illustrative dry-cooler/chiller-trim electricity model, not a vendor curve.

All coefficients and defaults are explicitly analyst assumptions. This is
a representative system, not an ESIF retrofit or calibrated facility.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PlantConfig:
    supply_c: float = 27.0
    dry_cooler_approach_c: float = 4.0
    transition_width_c: float = 5.0
    nominal_chiller_cop: float = 4.5
    cop_reference_ambient_c: float = 25.0
    cop_slope_per_c: float = 0.065
    cop_min: float = 2.5
    cop_max: float = 6.0
    fan_kw_per_kw_thermal: float = 0.025
    baseline_pump_kw: float = 8.0
    storage_pump_kw_per_panel: float = 0.001
    scenario_ambient_mean_c: float = 27.0
    scenario_ambient_swing_c: float = 6.0


def ambient_profile(timestamps: pd.Series, cfg: PlantConfig) -> np.ndarray:
    """Purely synthetic, labeled diurnal profile. Not measured weather."""
    h = pd.to_datetime(timestamps, utc=True).dt.hour.to_numpy(dtype=float)
    return cfg.scenario_ambient_mean_c + cfg.scenario_ambient_swing_c * np.sin(2 * np.pi * (h - 9) / 24)


def simulate_plant(
    thermal: pd.DataFrame,
    cfg: PlantConfig,
    *,
    panels: int,
    facility_it_kw: np.ndarray | None = None,
    ambient_c: np.ndarray | None = None,
) -> pd.DataFrame:
    if panels < 0 or cfg.transition_width_c <= 0 or cfg.nominal_chiller_cop <= 0:
        raise ValueError("Invalid plant geometry or performance parameters.")
    if cfg.cop_min <= 0 or cfg.cop_max < cfg.cop_min:
        raise ValueError("Require positive, ordered COP bounds.")
    if min(cfg.dry_cooler_approach_c, cfg.fan_kw_per_kw_thermal,
           cfg.baseline_pump_kw, cfg.storage_pump_kw_per_panel) < 0:
        raise ValueError("Plant cost/approach parameters cannot be negative.")
    n = len(thermal)
    if not n:
        raise ValueError("Empty thermal simulation.")
    ambient = ambient_profile(thermal.timestamp, cfg) if ambient_c is None else np.asarray(ambient_c, dtype=float)
    it = (thermal.it_power_kw.to_numpy(float) if facility_it_kw is None
          else np.asarray(facility_it_kw, dtype=float))
    if ambient.shape != (n,) or it.shape != (n,) or not np.isfinite(ambient).all() or not np.isfinite(it).all():
        raise ValueError("Ambient and facility IT profiles must be finite and match hourly workload.")
    if (it < 0).any():
        raise ValueError("IT demand cannot be negative.")
    # In this transparent piecewise-linear ASSUMPTION, ambient <= 18 C
    # permits full dry-cooling at 27 C supply (4 K approach + 5 K margin).
    dry_fraction = np.clip(
        (cfg.supply_c - cfg.dry_cooler_approach_c - ambient) / cfg.transition_width_c, 0, 1
    )
    cop = np.clip(cfg.nominal_chiller_cop -
                  cfg.cop_slope_per_c * (ambient - cfg.cop_reference_ambient_c),
                  cfg.cop_min, cfg.cop_max)

    out = pd.DataFrame({"timestamp": thermal.timestamp.to_numpy(),
                        "ambient_c": ambient, "free_cooling_fraction": dry_fraction,
                        "modeled_chiller_cop": cop,
                        "facility_it_electric_kw": it})
    for system, heat_col in (("none", "it_power_kw"),
                             ("water", "water_plant_thermal_kw"),
                             ("pcm", "pcm_plant_thermal_kw")):
        q = thermal[heat_col].to_numpy(float)
        if not np.isfinite(q).all() or (q < -1e-6).any():
            raise ValueError("Thermal heat-rejection loads must be finite and nonnegative.")
        q = np.maximum(q, 0)
        compressor = q * (1 - dry_fraction) / cop
        fans = q * cfg.fan_kw_per_kw_thermal
        if system == "none":
            pump_storage = np.zeros(n)
        else:
            col = f"{system}_storage_kw"
            pump_storage = (np.abs(thermal[col].to_numpy(float)) > 1e-9).astype(float) * (
                cfg.storage_pump_kw_per_panel * panels
            )
        cool_electric = compressor + fans + cfg.baseline_pump_kw + pump_storage
        out[f"{system}_compressor_kw"] = compressor
        out[f"{system}_cooling_electric_kw"] = cool_electric
        out[f"{system}_facility_electric_kw"] = it + cool_electric
        out[f"{system}_heat_rejection_kwth"] = q
    return out


def plant_summary(result: pd.DataFrame) -> dict:
    """Hourly series must be one-hour samples. No hidden seasonal uplift."""
    return {name: {
        "cooling_kwh_month": float(result[f"{name}_cooling_electric_kw"].sum()),
        "cooling_peak_kw": float(result[f"{name}_cooling_electric_kw"].max()),
        "facility_peak_kw": float(result[f"{name}_facility_electric_kw"].max()),
        "heat_rejection_peak_kwth": float(result[f"{name}_heat_rejection_kwth"].max()),
    } for name in ("none", "water", "pcm")}
