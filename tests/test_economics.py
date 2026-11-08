"""Economics tests use tiny hand-built hourly frames, so every expected number can be
checked by hand. They exercise arithmetic only and say nothing about real PCM performance."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from pcm.economics import (
    INPUT_META, KW_TH_PER_TON, PCM_PRICE_USD_PER_KG, EconInputs, evaluate, npv_grid,
    pcm_price_default, sensitivity,
)
from pcm.materials import MATERIALS
from pcm.thermal import Config

MAT = MATERIALS["na2so4"]
CFG = Config(panels=100)  # 5 m3 -> 7300 kg of Na2SO4.10H2O at 1460 kg/m3
K_E = 0.544 / KW_TH_PER_TON


def frame(pcm_storage, water_storage=0.0, hours=48, it=1000.0):
    """Constant IT load; storage kW is applied uniformly (or as an array) to each system."""
    ps = np.full(hours, pcm_storage, float) if np.isscalar(pcm_storage) else np.asarray(pcm_storage, float)
    ws = np.full(hours, water_storage, float) if np.isscalar(water_storage) else np.asarray(water_storage, float)
    itv = np.full(hours, it, float)
    return pd.DataFrame(dict(
        it_power_kw=itv, pcm_storage_kw=ps, water_storage_kw=ws,
        pcm_plant_thermal_kw=itv - ps, water_plant_thermal_kw=itv - ws,
    ))


def test_hand_calculated_case():
    inp = EconInputs(pcm_usd_per_kg=0.06)
    r = evaluate(frame(10.0), MAT, CFG, inp)
    tons = 10.0 / KW_TH_PER_TON
    assert r.delta_peak_kw == pytest.approx(10.0)
    assert r.avoided_tons == pytest.approx(tons)
    assert r.pcm_mass_kg == pytest.approx(7300.0)
    assert r.pcm_material_cost == pytest.approx(438.0)
    assert r.avoided_chiller_capex == pytest.approx(tons * 1000.0)
    assert r.net_capex == pytest.approx(438.0 - tons * 1000.0)
    assert r.demand_savings_year == pytest.approx(10.0 * K_E * 15.0 * 12.0)
    assert r.energy_savings_year == pytest.approx(0.0, abs=1e-9)
    assert r.annuity_factor == pytest.approx(3.992710, abs=1e-5)
    assert r.npv == pytest.approx(r.annual_savings * r.annuity_factor - r.net_capex)
    assert r.payback_years == 0.0  # cheaper up front than water


def test_flat_tariff_gives_no_energy_savings_even_with_unreleased_heat():
    # PCM stores 40 kWh more than it returns; that heat must not be booked as a saving.
    storage = np.zeros(48)
    storage[:8] = 10.0
    storage[20:28] = -5.0
    r = evaluate(frame(storage), MAT, CFG, EconInputs())
    assert r.energy_savings_year == pytest.approx(0.0, abs=1e-9)
    assert r.cooling_kwh_pcm_month == pytest.approx(r.cooling_kwh_water_month)


def test_time_of_use_tariff_rewards_shifting():
    hours = 48
    hour_of_day = np.arange(hours) % 24
    storage = np.where(hour_of_day >= 12, 10.0, -10.0)  # absorb in dear hours, release in cheap
    price = np.where(hour_of_day >= 12, 0.30, 0.10)
    r = evaluate(frame(storage), MAT, CFG, EconInputs(), hourly_price_usd_kwh=price)
    expected_window = K_E * 10.0 * 12 * (0.30 - 0.10) * 2  # kW x hours x price gap x 2 days
    assert r.energy_savings_year == pytest.approx(expected_window * 365.0 / 2.0)


def test_negative_peak_shave_is_a_cost_and_is_flagged():
    r = evaluate(frame(-10.0), MAT, CFG, EconInputs())
    assert r.delta_peak_kw == pytest.approx(-10.0)
    assert r.avoided_tons < 0 and r.avoided_chiller_capex < 0
    assert r.demand_savings_year < 0
    assert r.break_even_chiller_usd_per_ton is None
    assert any("RAISES" in w for w in r.warnings)


def test_break_even_pcm_price_zeroes_npv():
    r = evaluate(frame(10.0), MAT, CFG, EconInputs(pcm_usd_per_kg=0.06))
    assert r.break_even_pcm_usd_per_kg > 0
    again = evaluate(frame(10.0), MAT, CFG, EconInputs(pcm_usd_per_kg=r.break_even_pcm_usd_per_kg))
    assert again.npv == pytest.approx(0.0, abs=1e-6)


def test_break_even_containment_premium_zeroes_npv():
    r = evaluate(frame(10.0), MAT, CFG, EconInputs(pcm_usd_per_kg=0.06))
    assert r.break_even_extra_usd_per_m2 > 0
    again = evaluate(frame(10.0), MAT, CFG,
                     EconInputs(pcm_usd_per_kg=0.06, pcm_extra_usd_per_m2=r.break_even_extra_usd_per_m2))
    assert again.npv == pytest.approx(0.0, abs=1e-6)


def test_peaks_versus_no_storage_and_water_spike_warning():
    # PCM shaves 10 kW; water *raises* the peak by 20 kW. PCM "beats" water but only because water is worse
    # than doing nothing, and the result must say so.
    r = evaluate(frame(10.0, water_storage=-20.0), MAT, CFG, EconInputs())
    assert r.delta_peak_kw == pytest.approx(30.0)
    assert r.delta_peak_pcm_vs_none_kw == pytest.approx(10.0)
    assert r.delta_peak_water_vs_none_kw == pytest.approx(-20.0)
    assert any("water's dispatch spike" in w for w in r.warnings)


def test_pcm_peak_above_no_storage_is_flagged():
    r = evaluate(frame(-10.0, water_storage=-30.0), MAT, CFG, EconInputs())
    assert r.delta_peak_kw > 0  # looks like a win against water...
    assert r.delta_peak_pcm_vs_none_kw == pytest.approx(-10.0)  # ...but PCM is worse than no storage
    assert any("EXCEEDS" in w for w in r.warnings)


def test_break_even_chiller_cost_zeroes_npv():
    inp = EconInputs(pcm_usd_per_kg=5.0)  # expensive PCM, so a positive break-even chiller cost exists
    r = evaluate(frame(10.0), MAT, CFG, inp)
    assert r.break_even_chiller_usd_per_ton and r.break_even_chiller_usd_per_ton > 0
    again = evaluate(frame(10.0), MAT, CFG, replace(inp, chiller_usd_per_ton=r.break_even_chiller_usd_per_ton))
    assert again.npv == pytest.approx(0.0, abs=1e-6)


def test_npv_grid_matches_direct_evaluation():
    inp = EconInputs(pcm_usd_per_kg=0.5)
    base = evaluate(frame(10.0), MAT, CFG, inp)
    prices = np.array([0.1, 2.0])
    chillers = np.array([600.0, 2500.0])
    grid = npv_grid(base, prices, chillers)
    for i, c in enumerate(chillers):
        for j, p in enumerate(prices):
            direct = evaluate(frame(10.0), MAT, CFG, replace(inp, pcm_usd_per_kg=p, chiller_usd_per_ton=c))
            assert grid[i, j] == pytest.approx(direct.npv)


def test_cashflow_sums_to_npv():
    r = evaluate(frame(10.0), MAT, CFG, EconInputs(pcm_usd_per_kg=2.0))
    assert len(r.cashflow) == 6  # year 0 plus five years
    assert r.cashflow.discounted.sum() == pytest.approx(r.npv)
    assert r.cashflow.cumulative_discounted.iloc[-1] == pytest.approx(r.npv)


def test_zero_discount_rate_and_extra_containment():
    inp = EconInputs(discount_rate=0.0, pcm_extra_usd_per_m2=100.0, pcm_usd_per_kg=0.0)
    r = evaluate(frame(10.0), MAT, CFG, inp)
    assert r.annuity_factor == 5.0
    assert r.pcm_extra_cost == pytest.approx(100.0 * 100.0)  # 100 panels x 1 m2


def test_invalid_inputs_rejected():
    for bad in (dict(years=0), dict(chiller_kw_per_ton=0), dict(pcm_usd_per_kg=-1), dict(discount_rate=-1.5)):
        with pytest.raises(ValueError):
            evaluate(frame(10.0), MAT, CFG, EconInputs(**bad))
    with pytest.raises(ValueError):
        evaluate(frame(10.0), MAT, CFG, EconInputs(), hourly_price_usd_kwh=np.ones(3))


def test_sensitivity_brackets_base_case():
    inp = EconInputs(pcm_usd_per_kg=pcm_price_default("na2so4"))
    rows = sensitivity(frame(10.0), MAT, CFG, inp)
    assert {r["label"].split(" (")[0] for r in rows} >= {"PCM price", "Demand charge", "Discount rate"}
    price_row = next(r for r in rows if r["label"].startswith("PCM price"))
    assert price_row["npv_low"] > price_row["npv_high"]  # cheaper PCM, higher NPV


def test_every_material_has_a_price_range_and_provenance():
    assert set(PCM_PRICE_USD_PER_KG) == set(MATERIALS)
    for lo, mid, hi in PCM_PRICE_USD_PER_KG.values():
        assert lo <= mid <= hi
    assert INPUT_META["chiller_usd_per_ton"].status.startswith("placeholder")


def test_integration_with_thermal_simulation():
    from pcm.thermal import simulate
    dates = pd.date_range("2025-02-01", "2025-03-01", freq="h", inclusive="left", tz="UTC")
    load = pd.DataFrame({"timestamp": dates, "it_power_kw": 1000 + 40 * np.sin(np.arange(len(dates)) * 2 * np.pi / 24)})
    out = simulate(load, MAT, Config(panels=100, pcm_cells=6))
    r = evaluate(out, MAT, Config(panels=100, pcm_cells=6), EconInputs(pcm_usd_per_kg=0.06), synthetic=True)
    assert np.isfinite(r.npv)
    assert r.delta_peak_kw == pytest.approx(out.water_plant_thermal_kw.max() - out.pcm_plant_thermal_kw.max())
    assert r.peak_none_kw == pytest.approx(out.it_power_kw.max())
    assert any("synthetic" in w.lower() for w in r.warnings)
