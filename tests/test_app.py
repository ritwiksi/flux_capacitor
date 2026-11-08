import math
import pytest
import app
from pcm.annual import PRESETS, peak_week, run


@pytest.mark.parametrize("name", list(app.SCENARIOS))
def test_scenarios_run_through_ui_mapping(name):
    assert name in PRESETS
    k = run(app.YEAR, app.params_from_inputs(app.preset_inputs(name)))["kpis"]
    for key in ("saving_usd", "saving_pct", "chiller_avoided_kw", "pcm_capex_usd", "breakeven_usd_per_kg"):
        assert math.isfinite(k[key]), key
    assert k["payback_yr"] is None or math.isfinite(k["payback_yr"])


def test_scenarios_own_economiser():
    assert app.preset_inputs(app.SHOWCASE)["economiser"] is False
    assert app.preset_inputs(app.AS_BUILT)["economiser"] is True


def test_material_labels_short_and_unique():
    labels = list(app.MATERIAL_CHOICES.values())
    assert len(set(labels)) == len(app.MATERIAL_CHOICES)
    assert "Salt hydrate: Na₂SO₄·10H₂O" in labels and "Paraffin: RT35HC" in labels


def test_peak_week_chart_shows_pcm_cutting_the_peak():
    hourly = run(app.YEAR, app.params_from_inputs(app.preset_inputs(app.SHOWCASE)))["hourly"]
    w = peak_week(hourly)
    fig = app.week_figure(w)
    assert len(fig.data) == 3 and all(len(tr.y) == 168 for tr in fig.data)
    assert all(isinstance(v, str) and "Z" not in v and "+" not in v for v in fig.data[0].x)   # naive local time
    assert w.chiller_pcm_kw.max() < w.chiller_base_kw.max()
    assert app.week_summary(w).startswith("Peak week starting ")
