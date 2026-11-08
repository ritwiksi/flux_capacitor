import numpy as np
import pandas as pd
import pytest
from pcm.materials import MATERIALS, get_material
from pcm.thermal import Config, simulate, summarize
from pcm.workload import normalize_month


def month():
    dates = pd.date_range("2025-02-01", "2025-03-01", freq="h", inclusive="left", tz="UTC")
    return pd.DataFrame({"timestamp": dates, "it_power_kw": 1000 + np.arange(len(dates)) % 24})


def test_month_is_complete():
    assert len(normalize_month(month())) == 28*24


def test_reject_incomplete_month():
    with pytest.raises(ValueError, match="complete calendar month"):
        normalize_month(month().iloc[:-1])


def test_water_vs_pcm_repeated_cycles():
    df = month()
    config = Config(panels=100, pcm_cells=6)
    out = simulate(df, MATERIALS["rt35hc"], config)
    assert len(out) == len(df)
    assert out.pcm_melt_fraction.between(0, 1).all()
    assert (out.loc[out["mode"] == 0, ["pcm_storage_kw", "water_storage_kw"]].abs().max() < 1e-8).all()
    for x in ("pcm", "water"):
        assert np.allclose(out[f"{x}_plant_thermal_kw"],out.it_power_kw-out[f"{x}_storage_kw"])
    assert summarize(out)["pcm_heat_absorbed_kwh"] > 0


def test_regeneration_cap_prevents_new_cooling_peaks():
    df = month()
    peak = df.it_power_kw.max()
    for key in ("rt35hc", "na2so4"):
        capped = simulate(df, MATERIALS[key], Config(panels=1000, pcm_cells=6))
        assert capped.pcm_plant_thermal_kw.max() <= peak + 1e-6
        assert capped.water_plant_thermal_kw.max() <= peak + 1e-6
        s = summarize(capped)
        assert s["pcm_peak_thermal_shave_kw"] >= -1e-6 and s["water_peak_thermal_shave_kw"] >= -1e-6


def test_without_the_cap_regeneration_can_create_new_peaks():
    # Guards the test above: the uncapped (milestone 1) behaviour really does exceed the no-storage peak.
    df = month()
    uncapped = simulate(df, MATERIALS["rt35hc"], Config(panels=1000, pcm_cells=6, cap_regeneration=False))
    assert uncapped.water_plant_thermal_kw.max() > df.it_power_kw.max() + 1.0


def test_cap_only_limits_regeneration_not_charging():
    df = month()
    on = simulate(df, MATERIALS["na2so4"], Config(panels=1000, pcm_cells=6))
    off = simulate(df, MATERIALS["na2so4"], Config(panels=1000, pcm_cells=6, cap_regeneration=False))
    charging = on["mode"] == 1
    assert np.allclose(on.loc[charging & (on.index < 24), "pcm_storage_kw"],
                       off.loc[charging & (off.index < 24), "pcm_storage_kw"])  # day 1 charging identical
    regen = on["mode"] == -1
    headroom = df.it_power_kw.max() - on.loc[regen, "it_power_kw"]
    for col in ("pcm_storage_kw", "water_storage_kw"):
        assert (-on.loc[regen, col] <= headroom + 1e-6).all()
    # and the cap actually binds somewhere at this scale, otherwise this test proves nothing
    assert (-off.loc[regen, "pcm_storage_kw"] > headroom + 1e-6).any()


def test_graphite_is_identified_as_hypothetical():
    base = get_material("rt35hc")
    enhanced = get_material("rt35hc", True)
    assert enhanced.conductivity_w_m_k > base.conductivity_w_m_k
    assert "assumed" in enhanced.limitations.lower()


def test_water_capacity_reference():
    # 5m3 of water over 10C: 58.06kWh (independent of controller)
    assert 100*1.0*0.05*1000*4180*10/3.6e6 == pytest.approx(58.0556, abs=0.001)
