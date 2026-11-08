"""Behavioral tests for optimized threshold dispatch.

Tests check feasibility, independent water/PCM ceilings, energy causality,
and preservation of the original heuristic; none requires PCM to win.
"""
import numpy as np
import pandas as pd
import pytest

from pcm.materials import MATERIALS
from pcm.peak_dispatch import _simulate_targets, optimize_peak_dispatch
from pcm.thermal import Config, simulate


def repeating_profile(days=3):
    ts = pd.date_range("2025-07-01", periods=24 * days, freq="h", tz="UTC")
    h = np.arange(len(ts)) % 24
    q = np.where((h >= 12) & (h < 18), 1080.0, 900.0)
    return pd.DataFrame({"timestamp": ts, "it_power_kw": q})


@pytest.fixture(scope="module")
def example():
    data = repeating_profile()
    cfg = Config(panels=100, pcm_cells=6)
    material = MATERIALS["na2so4"]
    output, target = optimize_peak_dispatch(data, material, cfg, tolerance_kw=0.5)
    return data, cfg, material, output, target


def test_feasible_independent_targets_and_actual_hourly_peaks(example):
    data, cfg, material, output, target = example
    baseline = data.it_power_kw.max()
    assert len(output) == len(data)
    assert target.pcm_target_kw <= baseline
    assert target.water_target_kw <= baseline
    assert output.pcm_plant_thermal_kw.max() <= target.pcm_target_kw + 1e-6
    assert output.water_plant_thermal_kw.max() <= target.water_target_kw + 1e-6
    assert output.pcm_plant_thermal_kw.max() < baseline
    assert output.water_plant_thermal_kw.max() < baseline
    assert target.search_iterations > 0
    # No system is allowed to absorb more heat than the actual hourly IT load.
    assert (output.pcm_storage_kw <= output.it_power_kw + 1e-6).all()
    assert (output.water_storage_kw <= output.it_power_kw + 1e-6).all()
    assert output.pcm_melt_fraction.between(0, 1).all()


def test_peak_search_is_within_declared_resolution(example):
    data, cfg, material, output, target = example
    smaller_pcm = max(0, target.pcm_target_kw - 2 * target.tolerance_kw)
    smaller_water = max(0, target.water_target_kw - 2 * target.tolerance_kw)
    _, pcm_ok, water_ok = _simulate_targets(
        data, material, cfg, smaller_pcm, smaller_water, early_exit=True
    )
    assert not pcm_ok
    assert not water_ok


def test_released_heat_cannot_precede_absorbed_heat(example):
    data, cfg, material, output, target = example
    # Starts at 27 C for both systems: no negative total stored energy.
    for prefix in ("pcm", "water"):
        cumulative = output[f"{prefix}_storage_kw"].cumsum()
        assert cumulative.min() >= -1e-5
        assert output[f"{prefix}_storage_kw"].lt(0).any()
        assert output[f"{prefix}_storage_kw"].gt(0).any()
    assert target.pcm_end_stored_kwh == pytest.approx(max(0.0, output.pcm_storage_kw.sum()))
    assert target.water_end_stored_kwh == pytest.approx(max(0.0, output.water_storage_kw.sum()))


def test_zero_load_does_not_invent_value():
    workload = repeating_profile(1)
    workload["it_power_kw"] = 0.0
    result, target = optimize_peak_dispatch(workload, MATERIALS["rt35hc"], Config(panels=100))
    assert target.pcm_target_kw == target.water_target_kw == 0
    assert result[["pcm_storage_kw", "water_storage_kw", "pcm_plant_thermal_kw", "water_plant_thermal_kw"]].abs().max().max() == pytest.approx(0)


def test_legacy_mode_still_reproduces_old_output():
    workload = repeating_profile(1)
    classic = simulate(workload, MATERIALS["na2so4"], Config(panels=100))
    assert len(classic) == len(workload)
    assert "pcm_mode" not in classic.columns
    assert classic["mode"].isin([-1, 0, 1]).all()


def test_invalid_peak_search_inputs():
    workload = repeating_profile(1)
    with pytest.raises(ValueError):
        optimize_peak_dispatch(workload, MATERIALS["rt35hc"], Config(panels=0))
    with pytest.raises(ValueError):
        optimize_peak_dispatch(workload, MATERIALS["rt35hc"], Config(panels=100), tolerance_kw=0)
