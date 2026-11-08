"""Independent verification checks for pcm/annual.py (questions a judge could ask).

Expectations are computed BY HAND from the equations in CLAUDE.md and the property table in pcm/materials.py
(numbers typed in below), not by calling the helper under test. Only run, Params, PRESETS and load_year
are imported from the model. Every LP run is cached, so the whole file needs about 10 LP solves.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pcm.annual import PRESETS, Params, load_year, run

CSV = Path(__file__).resolve().parent.parent / "data" / "boston_2024_hourly.csv"
SHOWCASE = PRESETS["PCM showcase: chiller plant, salt hydrate, thin panels"]
DF = load_year()


# Plant and finance constants are PINNED here (hand-typed, the CLAUDE.md values at the time of writing) and passed
# explicitly, so the hand calculations below stay valid when the Params defaults move (they did: cop_slope 0.15 -> 0.2,
# demand 15 -> 27.5 USD/kW-month). The documented headline numbers are checked separately with the live defaults.
PIN = dict(it_mw=1.0, panel_area_m2=1.0, supply_c=27.0, return_c=37.0, h_w_m2k=150.0, cop_ref=6.0, cop_ref_twb_c=20.0,
           cop_slope=0.15, cop_min=3.0, approach_k=4.0, cop_free=25.0, demand_usd_per_kw_month=15.0,
           chiller_usd_per_kw=250.0, chiller_life_yr=20, pcm_life_yr=15, discount=0.07, graphite=False)


@lru_cache(maxsize=None)
def _run(**kw):
    return run(DF, Params(**{**PIN, **kw}))


def showcase(**over):
    return _run(**{**SHOWCASE, **over})


# Hand-typed constants (CLAUDE.md defaults; materials.py "na2so4" row). Do not import them from the model.
T_SUPPLY, T_RETURN = 27.0, 37.0
H_FLUID = 150.0                                  # W/m2K
NA2SO4 = dict(rho=1460.0, cp=1800.0, k=0.50, L=253_000.0, t_lo=31.4, t_hi=33.4)


def crf_by_hand(i, n):
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


# 1. Capacity -------------------------------------------------------------------------------------------------------
def test_showcase_capacity_by_hand():
    # A = 500 panels/MW * 1 MW * 1 m2 = 500 m2; m = 1460 * 500 * 0.020 = 14,600 kg
    # E_max = 14,600 * (253,000 + 1,800 * 10) / 3.6e6 = 1,099.06 kWh_th
    area = 500 * 1.0 * 1.0
    mass = NA2SO4["rho"] * area * 0.020
    e_max = mass * (NA2SO4["L"] + NA2SO4["cp"] * (T_RETURN - T_SUPPLY)) / 3.6e6
    assert mass == pytest.approx(14_600.0)
    assert e_max == pytest.approx(1099.0556, rel=1e-6)
    k = showcase()["kpis"]
    assert k["area_m2"] == pytest.approx(area)
    assert k["mass_kg"] == pytest.approx(mass, rel=1e-9)
    assert k["e_max_kwh"] == pytest.approx(e_max, rel=1e-9)
    assert k["pcm_capex_usd"] == pytest.approx(mass * 2.0)       # salt hydrate placeholder, 2 USD/kg


# 2. Conduction power limits ----------------------------------------------------------------------------------------
def test_showcase_power_limits_by_hand():
    # UA = 500 / (1/150 + 0.010/0.50) = 500 / 0.026667 = 18,750 W/K = 18.75 kW/K; T_melt_mid = 32.4 C
    # charge = 18.75 * (37 - 32.4) = 86.25 kW_th; regen = 18.75 * (32.4 - 27) = 101.25 kW_th
    ua_kw = 500 / (1 / H_FLUID + (0.020 / 2) / NA2SO4["k"]) / 1000
    t_melt = (NA2SO4["t_lo"] + NA2SO4["t_hi"]) / 2
    assert ua_kw == pytest.approx(18.75)
    k = showcase()["kpis"]
    assert k["p_charge_kw"] == pytest.approx(ua_kw * (T_RETURN - t_melt), rel=1e-9)    # 86.25
    assert k["p_regen_kw"] == pytest.approx(ua_kw * (t_melt - T_SUPPLY), rel=1e-9)     # 101.25
    assert k["p_charge_kw"] == pytest.approx(86.25) and k["p_regen_kw"] == pytest.approx(101.25)


# 3. Saturation time ------------------------------------------------------------------------------------------------
def _longest_run(mask):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def test_pcm_cannot_charge_at_full_power_longer_than_it_takes_to_fill():
    # Build guide: t_sat = m L / (Q_IT - Q_cool). Here the charge rate is capped at p_charge, so the fastest fill
    # is t_sat = E_max / p_charge = 1,099.06 / 86.25 = 12.7 h. Since 0 <= E <= E_max, the PCM can never sit at the
    # charge limit for more consecutive hours than that (+1 h tolerance for a partially full start).
    r = showcase()
    h, k = r["hourly"], r["kpis"]
    t_sat = k["e_max_kwh"] / k["p_charge_kw"]
    at_limit = (h.pcm_kw >= k["p_charge_kw"] - 1e-6).to_numpy()
    longest = _longest_run(at_limit)
    assert at_limit.any(), "PCM never charges at full power: check is vacuous"
    assert longest <= t_sat + 1, (longest, t_sat)
    # Same idea for discharge: E_max / p_regen = 10.9 h
    at_regen = (h.pcm_kw <= -k["p_regen_kw"] + 1e-6).to_numpy()
    assert _longest_run(at_regen) <= k["e_max_kwh"] / k["p_regen_kw"] + 1
    # And the storage really is used over its whole range (not stuck at one end)
    assert h.pcm_kwh.max() == pytest.approx(k["e_max_kwh"], rel=1e-3) and h.pcm_kwh.min() == pytest.approx(0, abs=1)


# 4. Free-cooling hours vs the weather file -------------------------------------------------------------------------
def stull_by_hand(t, rh):
    """Stull, R. (2011) J. Appl. Meteor. Climatol. 50, 2267, eq. 1 (written out independently)."""
    return (t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
            + np.arctan(t + rh)
            - np.arctan(rh - 1.676331)
            + 0.00391838 * np.power(rh, 1.5) * np.arctan(0.023101 * rh)
            - 4.686035)


def psychrometric_wet_bulb(t, rh, p_kpa=101.325):
    """Iterative psychrometer equation (no Stull): e_s(Tw) - A P (T - Tw) = e, FAO-56 Tetens e_s,
    ventilated-psychrometer A = 6.6e-4 (1 + 0.00115 Tw) per K. Bisection, 60 steps."""
    def es(x):
        return 0.6108 * np.exp(17.27 * x / (x + 237.3))
    e = rh / 100 * es(t)
    lo, hi = np.full_like(t, -60.0), t.copy()
    for _ in range(60):
        mid = (lo + hi) / 2
        g = es(mid) - 6.6e-4 * (1 + 0.00115 * mid) * p_kpa * (t - mid) - e
        hi, lo = np.where(g > 0, mid, hi), np.where(g > 0, lo, mid)
    return (lo + hi) / 2


def test_free_cooling_hours_match_weather_file():
    # Full free cooling (f = 1) iff T_wb <= T_return - approach - (T_return - T_supply) = 37 - 4 - 10 = 23 C
    raw = pd.read_csv(CSV)                                 # read the CSV again, independently of load_year
    twb = stull_by_hand(raw.temp_c.to_numpy(float), raw.rh_pct.to_numpy(float))
    threshold = T_RETURN - 4.0 - (T_RETURN - T_SUPPLY)
    expected_full = int((twb <= threshold).sum())
    expected_partial = int(((twb > threshold) & (twb < T_RETURN - 4.0)).sum())
    k = _run()["kpis"]                                     # default Params: economiser on, approach 4 K
    assert k["free_hours_full"] == expected_full == 8531   # CLAUDE.md / README quote 8,531 h
    assert k["free_hours_partial"] == expected_partial
    assert k["free_hours_full"] + k["free_hours_partial"] + int((twb >= T_RETURN - 4.0).sum()) == len(raw)


def test_stull_agrees_with_psychrometric_wet_bulb_where_it_matters():
    # Stull is an empirical fit (stated error about -1 to +0.65 K). In the warm hours, near the 23 C free-cooling
    # threshold, it should agree with a first-principles psychrometric solution to well under 0.5 K, so the
    # free-hour count is not an artefact of the fit. (Below 0 C the psychrometric version ignores ice, so skip.)
    t, rh = DF.temp_c.to_numpy(float), DF.rh_pct.to_numpy(float)
    st, ps = stull_by_hand(t, rh), psychrometric_wet_bulb(t, rh)
    warm = ps > 15
    assert np.abs(st - ps)[warm].max() < 0.5
    assert abs(int((st <= 23).sum()) - int((ps <= 23).sum())) <= 10    # measured: 8531 vs 8533


# 5. Direction checks -----------------------------------------------------------------------------------------------
def test_higher_demand_charge_never_reduces_saving():
    # Theorem (LP parametric cost): for optimal x1 at c1 and x2 at c2 > c1, (c2 - c1)(D2 - D1) <= 0, so the summed
    # monthly peak D of the PCM case is non-increasing in c_d. The saving itself is convex in c_d with slope
    # D_base - D_pcm; it is monotone only while the PCM does not raise the peak, so that part is an empirical
    # check on 2024 data, not a theorem.
    runs = {c: showcase(demand_usd_per_kw_month=c)["kpis"] for c in (0.0, 15.0, 30.0)}
    d_pcm = {c: r["pcm"]["demand_usd"] / c for c, r in runs.items() if c > 0}
    assert d_pcm[30.0] <= d_pcm[15.0] + 1e-3
    savings = [runs[c]["saving_usd"] for c in (0.0, 15.0, 30.0)]
    assert savings[0] <= savings[1] + 1e-3 and savings[1] <= savings[2] + 1e-3, savings


def test_more_panels_never_reduce_saving():
    # More area raises E_max, p_charge and p_regen together; the LP feasible set only grows and the baseline does not
    # change, so the optimal PCM total cost cannot rise (s = 0 stays feasible). saving_usd excludes PCM capex.
    s = [showcase(panels_per_mw=n)["kpis"] for n in (100, 500, 1000)]
    assert s[0]["base"]["total_usd"] == pytest.approx(s[2]["base"]["total_usd"])
    sav = [x["saving_usd"] for x in s]
    assert sav[0] <= sav[1] + 1e-3 and sav[1] <= sav[2] + 1e-3, sav
    assert sav[0] > 0


def test_economiser_never_worse_in_any_hour():
    # test_annual already checks the annual total. Pointwise: with f in [0,1], k_on = f/25 + (1-f)/COP <= 1/COP = k_off
    # because COP <= 6 + 0.15 * 40 = 12 < 25 for any Boston wet-bulb above -20 C.
    on, off = _run(panels_per_mw=0), _run(panels_per_mw=0, economiser=False)
    assert (on["hourly"].kwe_per_kwth <= off["hourly"].kwe_per_kwth + 1e-12).all()
    assert (on["hourly"].chiller_base_kw <= off["hourly"].chiller_base_kw + 1e-9).all()
    assert on["kpis"]["base"]["cooling_kwh"] <= off["kpis"]["base"]["cooling_kwh"]


# 6. Units and bookkeeping ------------------------------------------------------------------------------------------
def test_baseline_bookkeeping_by_hand():
    r = showcase()
    h, k, b = r["hourly"], r["kpis"], r["kpis"]["base"]
    # IT load: ESIF shape scaled so the peak is 1 MW = 1000 kW
    q = DF.it_kw_esif.to_numpy() / DF.it_kw_esif.max() * 1000.0
    assert np.allclose(h.q_it_kw, q) and h.q_it_kw.max() == pytest.approx(1000.0)
    # Economiser off: k = 1 / max(3, 6 - 0.15 (Twb - 20)), Twb from the independent Stull
    twb = stull_by_hand(DF.temp_c.to_numpy(float), DF.rh_pct.to_numpy(float))
    k_hand = 1 / np.maximum(3.0, 6.0 - 0.15 * (twb - 20.0))
    assert np.allclose(h.kwe_per_kwth, k_hand)
    grid = q + k_hand * q                                 # P_grid = P_IT + k Q_IT (kW_e)
    assert np.allclose(h.grid_base_kw, grid)
    price = DF.price_usd_per_kwh.to_numpy()
    assert b["energy_usd"] == pytest.approx((price * grid).sum(), rel=1e-9)    # USD/kWh * kW * 1 h
    assert b["cooling_kwh"] == pytest.approx((k_hand * q).sum(), rel=1e-9)
    # Demand: monthly max in local standard time (UTC-5) * 15 USD/kW-month
    local_month = (DF.index - np.timedelta64(5, "h")).month   # np, not pd.Timedelta: avoids a numpy deprecation warning
    peaks = pd.Series(grid, index=local_month).groupby(level=0).max()
    assert len(peaks) == 12
    assert b["demand_usd"] == pytest.approx(15.0 * peaks.sum(), rel=1e-9)
    # Chiller: no economiser, so chiller sized for full IT peak 1000 kW_th, annualised at CRF(7 %, 20 yr) = 0.09439
    assert b["chiller_kw"] == pytest.approx(1000.0)
    assert crf_by_hand(0.07, 20) == pytest.approx(0.094393, abs=1e-6)
    assert b["chiller_usd"] == pytest.approx(1000.0 * 250.0 * crf_by_hand(0.07, 20), rel=1e-9)
    assert b["total_usd"] == pytest.approx(b["energy_usd"] + b["demand_usd"] + b["chiller_usd"])
    # PUE = (IT + cooling) / IT
    assert k["pue_base"] == pytest.approx(1 + (k_hand * q).sum() / q.sum(), rel=1e-9)


def test_pcm_case_bookkeeping_and_finance_by_hand():
    r = showcase()
    h, k, p = r["hourly"], r["kpis"], r["kpis"]["pcm"]
    q, s, kf = h.q_it_kw.to_numpy(), h.pcm_kw.to_numpy(), h.kwe_per_kwth.to_numpy()
    grid = q + kf * (q - s)
    assert np.allclose(h.grid_pcm_kw, grid)
    assert p["energy_usd"] == pytest.approx((h.price.to_numpy() * grid).sum(), rel=1e-9)
    assert p["chiller_kw"] == pytest.approx((q - s).max(), rel=1e-9)            # f = 0 without economiser
    # Finance: payback = (PCM capex - avoided chiller capex) / annual opex saving;
    # break-even USD/kg = (opex saving / CRF(7 %, 15 yr) + avoided chiller capex) / mass
    opex = (k["base"]["energy_usd"] + k["base"]["demand_usd"]) - (p["energy_usd"] + p["demand_usd"])
    avoided_usd = (k["base"]["chiller_kw"] - p["chiller_kw"]) * 250.0
    assert k["opex_saving_usd"] == pytest.approx(opex)
    assert k["chiller_avoided_usd"] == pytest.approx(avoided_usd)
    assert k["payback_yr"] == pytest.approx((14_600 * 2.0 - avoided_usd) / opex, rel=1e-9)
    assert k["breakeven_usd_per_kg"] == pytest.approx((opex / crf_by_hand(0.07, 15) + avoided_usd) / 14_600, rel=1e-9)
    # Pinned values (15 USD/kW-month, COP slope 0.15) reproduce the original 192-run scan headline
    assert k["saving_usd"] == pytest.approx(4451, abs=1)
    assert k["chiller_avoided_kw"] == pytest.approx(57, abs=0.5)
    assert k["payback_yr"] == pytest.approx(4.8, abs=0.05)
    assert k["breakeven_usd_per_kg"] == pytest.approx(2.91, abs=0.005)


def test_documented_headline_numbers_match_live_defaults():
    # CLAUDE.md / README "Findings" quote these for the showcase and as-built presets with the CURRENT Params
    # defaults (27.5 USD/kW-month, COP slope 0.2). If a default changes, the docs must change with it.
    sc = run(DF, Params(**SHOWCASE))["kpis"]
    assert sc["saving_usd"] == pytest.approx(6209, abs=1)
    assert sc["saving_pct"] == pytest.approx(1.0, abs=0.05)
    assert sc["base"]["total_usd"] == pytest.approx(612_000, rel=0.01)
    assert sc["chiller_avoided_kw"] == pytest.approx(57, abs=0.5)
    assert sc["payback_yr"] == pytest.approx(3.1, abs=0.05)
    assert sc["breakeven_usd_per_kg"] == pytest.approx(4.01, abs=0.005)
    built = run(DF, Params(**PRESETS["Boston as built: free cooling on, paraffin defaults"]))["kpis"]
    assert built["saving_usd"] == pytest.approx(40, abs=0.5)
    assert built["base"]["total_usd"] == pytest.approx(548_000, rel=0.01)
    assert built["free_hours_full"] == 8531
