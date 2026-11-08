"""Time a complete synthetic month: optimization, cycle audit, plant and lifecycle."""
from pathlib import Path
from time import perf_counter

import pandas as pd

from pcm.cycles import audit_cycles
from pcm.lifecycle import LifecycleInputs, evaluate_lifecycle
from pcm.materials import MATERIALS
from pcm.peak_dispatch import optimize_peak_dispatch
from pcm.plant import PlantConfig, simulate_plant
from pcm.thermal import Config
from pcm.workload import normalize_month


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "sample_synthetic_2025_07.csv"
    df = normalize_month(pd.read_csv(path))
    cfg = Config(panels=100)
    mat = MATERIALS["cacl2"]
    timings = {}
    start = perf_counter()
    _, target = optimize_peak_dispatch(df, mat, cfg)
    timings["threshold_search_s"] = perf_counter() - start
    start = perf_counter()
    thermal, audit = audit_cycles(df, mat, cfg, target)
    timings["cyclic_audit_s"] = perf_counter() - start
    start = perf_counter()
    plant = simulate_plant(thermal, PlantConfig(), panels=cfg.panels)
    life = evaluate_lifecycle(plant, mat, cfg, LifecycleInputs(),
                              pcm_cycle_verified=audit.pcm_verified,
                              water_cycle_verified=audit.water_verified)
    timings["plant_and_lifecycle_s"] = perf_counter() - start
    print("DATA: 100-panel SYNTHETIC month; no site data")
    print("RUNTIME:", {name: round(t, 3) for name, t in timings.items()})
    print("CYCLE VERIFIED:", audit.pcm_verified, audit.water_verified,
          "audited periods", audit.passes)
    print("LAST-MONTH PEAKS (kWth):", float(thermal.pcm_plant_thermal_kw.max()),
          float(thermal.water_plant_thermal_kw.max()))
    print("CONSERVATIVE SCENARIO NPV (USD):", round(life.npv_usd, 2))


if __name__ == "__main__":
    main()
