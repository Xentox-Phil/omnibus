"""Assemble the analysis-ready feature table -> data/parquet/features.parquet.

Final pipeline stage. Concatenates every RVV stop-event parquet (the per-window
exports + the Line-1 full year) into one base table at STOP-EVENT grain, then
LEFT-joins the external context parquets so no row multiplies:

  weather    -> on local wall-clock hour of arrival (hourly grain)
  daylight   -> on operating_day
  holidays   -> on operating_day (pivoted to is_public_holiday / is_school_holiday)
  university -> on operating_day (pivoted to oth_in_session / ur_in_session)
  events     -> on operating_day (aggregated: event_count, attendance, names)
  strikes    -> on operating_day (strike_any + scope)

Idempotent: skips if features.parquet exists (use --force to rebuild).

Usage:
    uv run python pipeline/assemble.py
    uv run python pipeline/assemble.py --force
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

OUT_DIR = Path("data/parquet")
OUT = OUT_DIR / "features.parquet"

HOUR_FMT = "%Y-%m-%d %H"  # local wall-clock hour join key

# A stop-event window is identified by its schema, NOT a denylist: it carries
# raw event timestamps + stop identity at event grain. This stays correct when
# new context tables (lines, routes_osm, stop_times, …) land in data/parquet/.
# features.parquet shares the signature, so exclude the pipeline's own output.
WINDOW_SIGNATURE = {"ts_arrival_planned", "stop_code"}
SELF_OUTPUT = {"features.parquet"}


def rvv_parquets() -> list[Path]:
    out = []
    for p in sorted(OUT_DIR.glob("*.parquet")):
        if p.name in SELF_OUTPUT:
            continue
        cols = set(pl.scan_parquet(p).collect_schema().names())
        if WINDOW_SIGNATURE <= cols:
            out.append(p)
    return out


def base_table(paths: list[Path]) -> pl.LazyFrame:
    """Concat all RVV stop-event parquets, tagging each row with its source window."""
    frames = [
        pl.scan_parquet(p).with_columns(pl.lit(p.stem).alias("source_window"))
        for p in paths
    ]
    # diagonal_relaxed: tolerate minor column/dtype drift between the wide event
    # exports and the pivoted Line-1 table; missing cols become null.
    df = pl.concat(frames, how="diagonal_relaxed")
    # Hour key for the weather join: arrival at the door, else departure, else plan.
    join_ts = pl.coalesce(
        "ts_arrival_actual_door", "ts_departure_actual_door", "ts_arrival_planned"
    )
    return df.with_columns(join_ts.dt.strftime(HOUR_FMT).alias("_hour_key"))


def weather_ctx() -> pl.DataFrame:
    df = pl.read_parquet(OUT_DIR / "weather_regensburg.parquet")
    return df.with_columns(
        # weather ts is tz-aware Europe/Berlin; strip tz to keep wall-clock, matching
        # the naive RVV timestamps.
        pl.col("ts").dt.replace_time_zone(None).dt.strftime(HOUR_FMT).alias("_hour_key")
    ).select(
        "_hour_key", "temp_c", "precip_mm", "wind_kmh", "wind_gust_kmh",
        "weather_code", "humidity_pct", "cloud_cover_pct", "snowfall_cm",
    )


def daylight_ctx() -> pl.DataFrame:
    return pl.read_parquet(OUT_DIR / "daylight_regensburg.parquet").select(
        pl.col("date").alias("operating_day"),
        pl.col("sunrise").alias("sunrise_ts"),
        pl.col("sunset").alias("sunset_ts"),
        "daylight_hours",
    )


def holidays_ctx() -> pl.DataFrame:
    df = pl.read_parquet(OUT_DIR / "holidays_bavaria.parquet")
    return df.group_by("date").agg(
        (pl.col("kind") == "public").any().alias("is_public_holiday"),
        (pl.col("kind") == "school").any().alias("is_school_holiday"),
        pl.col("name").filter(pl.col("kind") == "public").first().alias("holiday_name"),
    ).rename({"date": "operating_day"})


def university_ctx() -> pl.DataFrame:
    df = pl.read_parquet(OUT_DIR / "university_calendar.parquet")
    wide = df.pivot(on="institution", index="date", values="in_session")
    rename = {c: f"{c}_in_session" for c in wide.columns if c != "date"}
    return wide.rename({**rename, "date": "operating_day"})


def events_ctx() -> pl.DataFrame:
    df = pl.read_parquet(OUT_DIR / "events_regensburg.parquet")
    return df.group_by("date").agg(
        pl.len().alias("event_count"),
        pl.col("approx_attendance").sum().alias("event_attendance_sum"),
        pl.col("approx_attendance").max().alias("event_attendance_max"),
        pl.col("event_name").str.join(" | ").alias("event_names"),
        pl.col("event_type").unique().str.join(" | ").alias("event_types"),
    ).with_columns(pl.lit(True).alias("has_event")).rename({"date": "operating_day"})


def strikes_ctx() -> pl.DataFrame:
    df = pl.read_parquet(OUT_DIR / "strikes_rvv.parquet")
    return df.group_by("date").agg(
        pl.lit(True).alias("strike_any"),
        pl.col("scope").unique().str.join(" | ").alias("strike_scope"),
    ).rename({"date": "operating_day"})


def stops_geo_ctx() -> tuple[pl.DataFrame, pl.DataFrame] | None:
    """RVV stop_code/stop_name -> lat/lon + kind from GTFS. Skip cleanly if absent.

    Returns (by_code, by_name). The primary join is on stop_code (RVV's clean
    operator key); by_name backfills the ~127k rows where stop_code is null
    (Apr-2025 Line-1 ingest defect, see docs/DATA_DEFECTS.md).
    """
    p = OUT_DIR / "stops_geo.parquet"
    if not p.exists():
        return None
    geo = pl.read_parquet(p)
    by_code = geo.select("stop_code", "stop_lat", "stop_lon", pl.col("kind").alias("stop_kind"))
    by_name = (
        geo.filter(pl.col("stop_lat").is_not_null())
        .select("stop_name", "stop_lat", "stop_lon")
        .unique(subset=["stop_name"], keep="first")
        .rename({"stop_lat": "stop_lat_nm", "stop_lon": "stop_lon_nm"})
    )
    return by_code, by_name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild even if features.parquet exists")
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f"{OUT} exists — skip (use --force to rebuild).")
        return

    paths = rvv_parquets()
    if not paths:
        raise SystemExit(f"no RVV stop-event parquets in {OUT_DIR} — run ingest first.")
    print(f"base: {len(paths)} RVV parquet(s)")

    lf = base_table(paths)
    lf = lf.join(weather_ctx().lazy(), on="_hour_key", how="left")
    for ctx in (daylight_ctx, holidays_ctx, university_ctx, events_ctx, strikes_ctx):
        lf = lf.join(ctx().lazy(), on="operating_day", how="left")

    geo = stops_geo_ctx()
    if geo is None:
        print("  (no stops_geo.parquet — features will lack stop_lat/stop_lon. Run fetch_gtfs.py.)")
    else:
        by_code, by_name = geo
        lf = (
            lf.join(by_code.lazy(), on="stop_code", how="left")
            .join(by_name.lazy(), on="stop_name", how="left")
            .with_columns(
                stop_lat=pl.coalesce("stop_lat", "stop_lat_nm"),
                stop_lon=pl.coalesce("stop_lon", "stop_lon_nm"),
            )
            .drop("stop_lat_nm", "stop_lon_nm")
        )
    # Fill the existence flags that are null where no event/strike that day.
    lf = lf.with_columns(
        pl.col("has_event").fill_null(False),
        pl.col("strike_any").fill_null(False),
        pl.col("is_public_holiday").fill_null(False),
        pl.col("is_school_holiday").fill_null(False),
        pl.col("event_count").fill_null(0),
    ).drop("_hour_key")

    df = lf.collect(engine="streaming")

    # Cleanse non-passenger rows: depot / subcontractor / test / operational
    # stop_codes (stop_kind != 'stop', see docs/CONTACT_NOTES.md). The raw window
    # parquets keep them; only this modelling table is filtered. Unknown codes
    # (null stop_kind — none today, but future-proof) are kept, not silently cut.
    if "stop_kind" in df.columns:
        before = df.height
        df = df.filter(pl.col("stop_kind").is_null() | (pl.col("stop_kind") == "stop"))
        dropped = before - df.height
        if dropped:
            print(f"  [clean] dropped {dropped:,} non-passenger rows "
                  f"(depot/operational/test) → {df.height:,} passenger stop-events")

    # Trip-boundary flags, computed on the cleansed rows so `is_last_stop` marks
    # the real terminus (last passenger stop), not the dropped depot. Terminus
    # dwell is layover (~17× interior median), not passenger demand — flag so
    # dwell→demand analysis can exclude it without dropping the row. (DATA_DEFECTS §4)
    df = df.with_columns(
        (pl.col("stop_seq") == pl.col("stop_seq").min().over("trip_id")).alias("is_first_stop"),
        (pl.col("stop_seq") == pl.col("stop_seq").max().over("trip_id")).alias("is_last_stop"),
    ).with_columns(
        (pl.col("is_first_stop") | pl.col("is_last_stop")).alias("is_terminus")
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT, compression="zstd")
    print(f"  -> {OUT}: {df.height:,} rows × {df.width} cols ({OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
