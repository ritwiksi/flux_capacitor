import pandas as pd
from pcm.workload import normalize_month


def test_esif_timestamps_parse_to_utc():
    # A full UTC month (Feb 2016, leap year) written the way NLR/ESIF stores it: local MST with a JS-style suffix.
    utc = pd.date_range("2016-02-01", "2016-03-01", freq="h", inclusive="left", tz="UTC")
    local = utc.tz_convert("Etc/GMT+7")
    ts = [t.strftime("%a %b %d %Y %H:%M:%S GMT-0700 (Mountain Standard Time)") for t in local]
    out = normalize_month(pd.DataFrame({"ts": ts, "it_power_kw": 1000.0}))
    assert len(out) == 29 * 24
    assert (pd.DatetimeIndex(out.timestamp) == utc).all()


def test_iso_timestamps_still_parse():
    utc = pd.date_range("2025-04-01", "2025-05-01", freq="h", inclusive="left", tz="UTC")
    ts = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = normalize_month(pd.DataFrame({"timestamp": ts, "it_power_kw": 500.0}))
    assert len(out) == 30 * 24
    assert out.timestamp.iloc[0] == pd.Timestamp("2025-04-01", tz="UTC")
