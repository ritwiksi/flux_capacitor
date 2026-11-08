"""Build data/boston_2024_hourly.csv: one UTC-hourly table for the annual cost model.

Inputs (downloaded separately, not committed):
  --weather  NSRDB GOES Conus v4 CSV for Boston 2024 (POINT(-71.06 42.36), interval=60, utc=false)
  --esif     hourly IT power derived from the NLR/ESIF PUE zip (columns: ts, it_power_kw; UTC)
  --isone    folder of ISO-NE day-ahead hourly LMP JSON, location 4008 (.Z.NEMASSBOST), one file per day
Gap rule for ESIF: readings < 10 % of the median are glitches; every missing hour is copied from the same
hour one week earlier (else later). Filled hours are flagged in `it_filled`; nothing is silently invented.

Usage: python -m scripts.prepare_boston_2024 --weather W.csv --esif E.csv --isone DIR [--out data/boston_2024_hourly.csv]
"""
import argparse
import json
from pathlib import Path
import pandas as pd

# Boston calendar year 2024 in local standard time (EST = UTC-5), stored as UTC: matches all three sources.
HOURS = pd.date_range("2024-01-01 05:00", periods=8784, freq="h", tz="UTC")


def weather(path: Path) -> pd.DataFrame:
    w = pd.read_csv(path, skiprows=2)  # 2 NSRDB metadata rows
    std = pd.to_datetime(w[["Year", "Month", "Day", "Hour"]].rename(columns=str.lower))
    w.index = std.dt.tz_localize("Etc/GMT+5").dt.tz_convert("UTC")  # fetched as local standard time (UTC-5)
    return w.rename(columns={"Temperature": "temp_c", "Relative Humidity": "rh_pct"})[["temp_c", "rh_pct"]]


def esif(path: Path) -> pd.DataFrame:
    s = pd.read_csv(path, index_col=0, parse_dates=True)["it_power_kw"].reindex(HOURS)
    s = s.where(s >= 0.1 * s.median())
    filled = s.isna()
    for _ in range(60):  # walk one week at a time until every gap is covered
        if not s.isna().any():
            break
        s = s.fillna(s.shift(168)).fillna(s.shift(-168))
    assert not s.isna().any(), "ESIF gaps could not be filled from neighbouring weeks"
    return pd.DataFrame({"it_kw_esif": s, "it_filled": filled})


def prices(folder: Path) -> pd.Series:
    rows = []
    for f in sorted(folder.glob("da_4008_2024*.json")):
        for h in json.loads(f.read_text())["HourlyLmps"]["HourlyLmp"]:
            rows.append((pd.Timestamp(h["BeginDate"]).tz_convert("UTC"), h["LmpTotal"] / 1000))
    return pd.Series(dict(rows), name="price_usd_per_kwh").sort_index()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--weather", type=Path, required=True)
    p.add_argument("--esif", type=Path, required=True)
    p.add_argument("--isone", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("data/boston_2024_hourly.csv"))
    a = p.parse_args()
    df = weather(a.weather).reindex(HOURS).join(prices(a.isone).reindex(HOURS)).join(esif(a.esif))
    missing = df.drop(columns="it_filled").isna().sum()
    assert not missing.any(), f"missing hours after join:\n{missing}"
    df.index.name = "utc"
    df.round(5).to_csv(a.out)
    print(f"{len(df)} hours -> {a.out} | ESIF hours filled: {int(df.it_filled.sum())}")


if __name__ == "__main__":
    main()
