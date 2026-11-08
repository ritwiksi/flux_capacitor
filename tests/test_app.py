import math
import pytest
import app
from pcm.annual import PRESETS, run


@pytest.mark.parametrize("name", list(PRESETS))
def test_presets_run_through_ui_mapping(name):
    k = run(app.YEAR, app.params_from_inputs(app.preset_inputs(name)))["kpis"]
    for key in ("saving_usd", "saving_pct", "pue_base", "pue_pcm", "pcm_capex_usd", "breakeven_usd_per_kg"):
        assert math.isfinite(k[key]), key
    assert k["payback_yr"] is None or math.isfinite(k["payback_yr"])
