import numpy as np
import pytest
from pcm.annual import Params, load_year, run, wet_bulb_c

DF = load_year()


def test_input_year_complete():
    assert len(DF) == 8784 and not DF.drop(columns="it_filled").isna().any().any()


def test_wet_bulb_reference_point():
    # Stull (2011): 20 C, 50 % RH -> about 13.7 C
    assert wet_bulb_c(20, 50) == pytest.approx(13.7, abs=0.1)


@pytest.mark.parametrize("material", ["rt35hc", "rt28hc", "cacl2", "na2so4"])
def test_energy_balance_bounds_and_no_worse_than_baseline(material):
    r = run(DF, Params(material=material, panels_per_mw=2000))
    h, k = r["hourly"], r["kpis"]
    # PCM only shifts heat: total chiller+tower heat removed equals total IT heat (cyclic storage)
    assert (h.q_it_kw - h.pcm_kw).sum() == pytest.approx(h.q_it_kw.sum(), rel=1e-6)
    assert h.pcm_kwh.between(-1e-6, k["e_max_kwh"] + 1e-6).all()
    assert h.pcm_kw.between(-k["p_regen_kw"] - 1e-6, k["p_charge_kw"] + 1e-6).all()
    assert k["pcm"]["total_usd"] <= k["base"]["total_usd"] + 1e-6   # s = 0 is always feasible


def test_no_pcm_equals_baseline():
    k = run(DF, Params(panels_per_mw=0))["kpis"]
    assert k["saving_usd"] == pytest.approx(0, abs=1e-9)
    assert np.isclose(k["pue_base"], k["pue_pcm"])


def test_economiser_reduces_cooling_energy():
    on = run(DF, Params(panels_per_mw=0))["kpis"]
    off = run(DF, Params(panels_per_mw=0, economiser=False))["kpis"]
    assert off["free_hours_full"] == 0 and on["free_hours_full"] > 0
    assert on["base"]["cooling_kwh"] < off["base"]["cooling_kwh"]
