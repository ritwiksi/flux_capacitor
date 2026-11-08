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


def test_graphite_is_identified_as_hypothetical():
    base = get_material("rt35hc")
    enhanced = get_material("rt35hc", True)
    assert enhanced.conductivity_w_m_k > base.conductivity_w_m_k
    assert "assumed" in enhanced.limitations.lower()


def test_water_capacity_reference():
    # 5m3 of water over 10C: 58.06kWh (independent of controller)
    assert 100*1.0*0.05*1000*4180*10/3.6e6 == pytest.approx(58.0556, abs=0.001)
