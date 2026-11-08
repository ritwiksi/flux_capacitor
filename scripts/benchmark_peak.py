"""Measure actual wall-clock runtime without claiming universal speed.

Run: python -m scripts.benchmark_peak
Uses the explicitly synthetic sample, with default 100 panels and 27/37 C.
"""
from pathlib import Path
from time import perf_counter

import pandas as pd

from pcm.materials import MATERIALS
from pcm.peak_dispatch import optimize_peak_dispatch
from pcm.thermal import Config
from pcm.workload import normalize_month


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "sample_synthetic_2025_07.csv"
    workload = normalize_month(pd.read_csv(path))
    config = Config(panels=100)
    start = perf_counter()
    result, search = optimize_peak_dispatch(workload, MATERIALS["na2so4"], config)
    seconds = perf_counter() - start
    print(f"SYNTHETIC demo: {len(result)} hourly rows, {search.search_iterations} search iterations")
    print(f"Runtime on this machine: {seconds:.2f} seconds (actual, not a fixed progress estimate)")
    print(f"PCM threshold: {search.pcm_target_kw:.2f} thermal kW")
    print(f"Water threshold: {search.water_target_kw:.2f} thermal kW")
    print(f"No-storage baseline: {workload.it_power_kw.max():.2f} thermal kW")
    print(f"End stored: PCM {search.pcm_end_stored_kwh:.2f}, water {search.water_end_stored_kwh:.2f} thermal kWh")


if __name__ == "__main__":
    main()
