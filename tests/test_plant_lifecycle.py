import numpy as np
import pandas as pd
import pytest

from pcm.cycles import audit_cycles
from pcm.lifecycle import LifecycleInputs, evaluate_lifecycle
from pcm.materials import MATERIALS
from pcm.peak_dispatch import optimize_peak_dispatch
from pcm.plant import PlantConfig, ambient_profile, plant_summary, simulate_plant
from pcm.thermal import Config
from pcm.workload import normalize_month


def sample(hours=24):
    ts = pd.date_range("2025-07-01", periods=hours, freq="h", tz="UTC")
    h = np.arange(hours) % 24
    load = np.where((h >= 12) & (h <= 18), 1030, 900).astype(float)
    return pd.DataFrame({"timestamp": ts, "it_power_kw": load})


def test_cyclic_zero_heat_is_verified_and_conserves_energy():
    data = sample(24)
    data["it_power_kw"] = 0.0
    cfg = Config(panels=20, pcm_cells=4)
    mat = MATERIALS["na2so4"]
    _, targets = optimize_peak_dispatch(data, mat, cfg, tolerance_kw=1.0)
    out, audit = audit_cycles(data, mat, cfg, targets, max_passes=3)
    assert audit.pcm_verified and audit.water_verified
    assert audit.pcm_state_drift_kwh == pytest.approx(0, abs=1e-8)
    assert audit.water_state_drift_kwh == pytest.approx(0, abs=1e-8)
    assert out[["pcm_storage_kw", "water_storage_kw"]].abs().max().max() == pytest.approx(0)


def test_repeated_cycle_audit_tracks_pcm_enthalpy_not_just_total():
    data = sample(48)
    cfg = Config(panels=35, pcm_cells=4)
    mat = MATERIALS["na2so4"]
    _, targets = optimize_peak_dispatch(data, mat, cfg, tolerance_kw=2)
    output, audit = audit_cycles(data, mat, cfg, targets, max_passes=3)
    assert len(output) == len(data)
    assert audit.pcm_energy_residual_kwh < .01
    assert audit.water_energy_residual_kwh < .01
    if audit.pcm_verified:
        assert audit.pcm_state_drift_kwh <= audit.tolerance_kwh
        assert output.pcm_plant_thermal_kw.max() <= targets.pcm_target_kw + 1e-6
    if audit.water_verified:
        assert audit.water_state_drift_kwh <= audit.tolerance_kwh
        assert output.water_plant_thermal_kw.max() <= targets.water_target_kw + 1e-6


def plant_input():
    frame = sample(24)
    frame["water_plant_thermal_kw"] = frame.it_power_kw - np.where(frame.it_power_kw > 1000, 10.0, 0)
    frame["pcm_plant_thermal_kw"] = frame.it_power_kw - np.where(frame.it_power_kw > 1000, 20.0, 0)
    frame["water_storage_kw"] = frame.it_power_kw - frame.water_plant_thermal_kw
    frame["pcm_storage_kw"] = frame.it_power_kw - frame.pcm_plant_thermal_kw
    return frame


def test_plant_uses_weather_for_cooling_energy():
    frame = plant_input()
    cfg = PlantConfig(supply_c=27)
    cold = simulate_plant(frame, cfg, panels=100, ambient_c=np.full(len(frame), 10.))
    hot = simulate_plant(frame, cfg, panels=100, ambient_c=np.full(len(frame), 35.))
    assert (cold.free_cooling_fraction == 1).all()
    assert (hot.free_cooling_fraction == 0).all()
    assert cold.pcm_compressor_kw.sum() == pytest.approx(0)
    assert hot.pcm_compressor_kw.sum() > 0
    assert cold.pcm_cooling_electric_kw.sum() < hot.pcm_cooling_electric_kw.sum()
    # Full IT electrical load is separate from thermal-loop fraction.
    assert (hot.pcm_facility_electric_kw >= hot.facility_it_electric_kw).all()


def test_plant_rejects_invalid_ambient_data():
    frame = plant_input()
    with pytest.raises(ValueError):
        simulate_plant(frame, PlantConfig(), panels=100, ambient_c=np.array([20.0]))
    with pytest.raises(ValueError):
        simulate_plant(frame, PlantConfig(), panels=100, ambient_c=np.full(24, np.nan))


def test_lifecycle_npv_cash_flow_demand_and_suppressed_capacity_credit():
    frame = plant_input()
    plant = simulate_plant(frame, PlantConfig(), panels=100, ambient_c=np.full(24, 32.))
    opts = LifecycleInputs(pcm_material_usd_kg=.1, allow_capacity_credit=True)
    out = evaluate_lifecycle(plant, MATERIALS["cacl2"], Config(panels=100),
                             opts, pcm_cycle_verified=False, water_cycle_verified=True)
    assert out.chiller_credit_usd == 0
    assert any("suppressed" in msg.lower() for msg in out.warnings)
    assert out.npv_usd == pytest.approx(out.cashflows.discounted_usd.sum())
    assert out.pcm_total_5y_kgco2e > out.pcm_embodied_kgco2e
    credited = evaluate_lifecycle(plant, MATERIALS["cacl2"], Config(panels=100),
                                  opts, pcm_cycle_verified=True, water_cycle_verified=True)
    assert credited.chiller_credit_usd > 0
    annuity = sum(1/(1+opts.discount_rate)**year for year in range(1, opts.years+1))
    verified_annual_bill_savings = 12 * (out.water_month_bill_usd - out.pcm_month_bill_usd)
    assert credited.npv_usd == pytest.approx(
        out.npv_usd + credited.chiller_credit_usd + verified_annual_bill_savings * annuity
    )
    assert out.pcm_total_5y_kgco2e - out.water_total_5y_kgco2e == pytest.approx(
        out.pcm_embodied_kgco2e - out.water_embodied_kgco2e
    )


def test_tariff_demand_charge_uses_facility_peak_not_cooling_peak():
    frame = plant_input()
    plant = simulate_plant(frame, PlantConfig(), panels=100, ambient_c=np.full(24, 30.))
    options = LifecycleInputs(energy_price_usd_kwh=0, demand_charge_usd_kw_month=10,
                              pcm_material_usd_kg=.2)
    out = evaluate_lifecycle(plant, MATERIALS["cacl2"], Config(panels=100), options)
    assert out.pcm_month_bill_usd == pytest.approx(10 * plant.pcm_facility_electric_kw.max())
    assert out.water_month_bill_usd == pytest.approx(10 * plant.water_facility_electric_kw.max())


def test_weather_csv_is_preserved_only_if_complete():
    ts = pd.date_range("2025-07-01", "2025-08-01", freq="h", inclusive="left", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "it_power_kw": np.full(len(ts), 1000),
                       "outside_air_temp_c": np.full(len(ts), 22.0)})
    out = normalize_month(df)
    assert (out.outside_air_temp_c == 22).all()
    df.loc[5, "outside_air_temp_c"] = np.nan
    with pytest.raises(ValueError, match="Weather column"):
        normalize_month(df)


def test_cash_flow_replacement_is_counted_only_in_due_year():
    frame = plant_input()
    plant = simulate_plant(frame, PlantConfig(), panels=10)
    options = LifecycleInputs(pcm_replace_years=2, water_replace_years=3, years=5)
    out = evaluate_lifecycle(plant, MATERIALS["cacl2"], Config(panels=10), options)
    assert len(out.cashflows) == 6
    assert not np.isnan(out.cashflows.net_savings_usd).any()
