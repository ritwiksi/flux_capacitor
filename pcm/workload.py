"""Strict, reproducible hourly load profile preprocessing."""
import calendar
import pandas as pd


def normalize_month(raw: pd.DataFrame) -> pd.DataFrame:
    """Select the earliest *complete* calendar month, deterministically.

    CSV must carry `timestamp` (or `ts`) and `it_power_kw`, in UTC. The data is
    averaged into one-hour intervals. Months with missing hours are skipped,
    not interpolated. This prevents selection of flattering time windows.
    """
    df = raw.rename(columns={"ts": "timestamp"}).copy()
    if not {"timestamp", "it_power_kw"}.issubset(df.columns):
        raise ValueError("CSV needs timestamp (or ts) and it_power_kw columns.")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["it_power_kw"] = pd.to_numeric(df["it_power_kw"], errors="coerce")
    df = df.dropna(subset=["timestamp", "it_power_kw"])
    df = df.loc[df["it_power_kw"] >= 0]
    if df.empty:
        raise ValueError("No valid nonnegative IT power measurements.")
    # A full hour needs at least one valid sample; no invented or filled gaps.
    series = df.set_index("timestamp")["it_power_kw"].sort_index().resample("1h").mean()
    years_months = sorted(set(zip(series.index.year, series.index.month)))
    for year, month in years_months:
        start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        length = calendar.monthrange(year, month)[1] * 24
        idx = pd.date_range(start, periods=length, freq="h")
        candidate = series.reindex(idx)
        if candidate.notna().all():
            out = pd.DataFrame({"timestamp": idx, "it_power_kw": candidate.values})
            # Optional outside-air °C; validate coverage, never silently fill holes.
            if "outside_air_temp_c" in df.columns:
                weather = pd.to_numeric(df["outside_air_temp_c"], errors="coerce")
                weather_hourly = (pd.DataFrame({"timestamp": df["timestamp"], "temp": weather})
                                  .dropna().set_index("timestamp")["temp"]
                                  .sort_index().resample("1h").mean().reindex(idx))
                if weather_hourly.notna().all() and weather_hourly.between(-80, 65).all():
                    out["outside_air_temp_c"] = weather_hourly.values
                elif weather_hourly.notna().any():
                    raise ValueError("Weather column is incomplete or out of range; provide complete outside_air_temp_c or omit it.")
            return out
    raise ValueError("No complete calendar month found. Supply a full month of hourly IT power readings (UTC); missing hours are not filled.")
