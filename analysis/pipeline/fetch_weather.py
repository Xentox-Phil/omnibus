"""Fetch hourly weather + daily daylight for Regensburg from Open-Meteo -> Parquet.

Writes two parquets in one API roundtrip:
  - data/parquet/weather_regensburg.parquet  (hourly vars)
  - data/parquet/daylight_regensburg.parquet (daily sunrise, sunset, daylight)

Idempotent: skips fetch if BOTH parquets already exist (use --force to refetch).
Covers all RVV dataset windows (2023-2026) by default; override with --start/--end.

Usage:
    .venv/bin/python pipeline/fetch_weather.py            # fetch if missing
    .venv/bin/python pipeline/fetch_weather.py --force    # refetch
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import polars as pl

# Regensburg (see CLAUDE.md).
LAT, LNG = 49.013, 12.101
TZ = "Europe/Berlin"

OUT = Path("data/parquet/weather_regensburg.parquet")
OUT_DAILY = Path("data/parquet/daylight_regensburg.parquet")
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Hourly variables we care about. Names match Open-Meteo's API.
HOURLY_VARS = [
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "visibility",
    "weather_code",
    "relative_humidity_2m",
    "cloud_cover",
    "snowfall",
]

# Daily variables: sunrise/sunset for night-vs-day ridership analysis.
DAILY_VARS = ["sunrise", "sunset", "daylight_duration"]

# Rename to our naming convention on write.
RENAME = {
    "time": "ts",
    "temperature_2m": "temp_c",
    "precipitation": "precip_mm",
    "wind_speed_10m": "wind_kmh",
    "wind_gusts_10m": "wind_gust_kmh",
    "visibility": "visibility_m",
    "weather_code": "weather_code",
    "relative_humidity_2m": "humidity_pct",
    "cloud_cover": "cloud_cover_pct",
    "snowfall": "snowfall_cm",
}


def fetch(start: dt.date, end: dt.date) -> dict:
    params = {
        "latitude": LAT,
        "longitude": LNG,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(HOURLY_VARS),
        "daily": ",".join(DAILY_VARS),
        "timezone": TZ,
        "wind_speed_unit": "kmh",
    }
    url = f"{ARCHIVE_URL}?{urllib.parse.urlencode(params)}"
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            print(f"  attempt {attempt + 1} failed: {e}; retrying...")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Open-Meteo fetch failed after 3 attempts: {last}")


def to_dataframe(payload: dict) -> pl.DataFrame:
    hourly = payload["hourly"]
    df = pl.DataFrame(hourly)
    df = df.rename({k: v for k, v in RENAME.items() if k in df.columns})
    # Open-Meteo emits local-time strings including the skipped spring-forward
    # hour and the duplicated fall-back hour. Tell polars how to handle both.
    df = df.with_columns(
        pl.col("ts")
        .str.to_datetime("%Y-%m-%dT%H:%M")
        .dt.replace_time_zone(TZ, non_existent="null", ambiguous="earliest"),
        pl.col("weather_code").cast(pl.Int64, strict=False),
    )
    return df.drop_nulls("ts").sort("ts")


def to_daily_dataframe(payload: dict) -> pl.DataFrame:
    """Build the daily sunrise/sunset/daylight parquet from the same payload."""
    daily = payload["daily"]
    df = pl.DataFrame(daily).rename({"time": "date"})
    df = df.with_columns(
        pl.col("date").str.to_date("%Y-%m-%d"),
        # sunrise/sunset are local-time ISO strings; DST-safe with the same flags.
        pl.col("sunrise")
        .str.to_datetime("%Y-%m-%dT%H:%M")
        .dt.replace_time_zone(TZ, non_existent="null", ambiguous="earliest"),
        pl.col("sunset")
        .str.to_datetime("%Y-%m-%dT%H:%M")
        .dt.replace_time_zone(TZ, non_existent="null", ambiguous="earliest"),
        (pl.col("daylight_duration") / 3600.0).alias("daylight_hours"),
    )
    return df.drop("daylight_duration").sort("date")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01", help="ISO date (inclusive)")
    ap.add_argument(
        "--end",
        default=(dt.date.today() - dt.timedelta(days=2)).isoformat(),
        help="ISO date (inclusive); archive lags ~2 days",
    )
    ap.add_argument("--force", action="store_true", help="refetch even if parquet exists")
    args = ap.parse_args()

    if OUT.exists() and OUT_DAILY.exists() and not args.force:
        print(f"{OUT} + {OUT_DAILY} exist — skip. Use --force to refetch.")
        return

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    print(f"fetching Open-Meteo {start} -> {end} for Regensburg ({LAT}, {LNG})...")
    payload = fetch(start, end)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df = to_dataframe(payload)
    df.write_parquet(OUT, compression="zstd")
    print(f"  {df.height:,} hourly rows -> {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")

    df_daily = to_daily_dataframe(payload)
    df_daily.write_parquet(OUT_DAILY, compression="zstd")
    print(f"  {df_daily.height:,} daily rows -> {OUT_DAILY} ({OUT_DAILY.stat().st_size / 1e3:.1f} kB)")


if __name__ == "__main__":
    main()
