"""Build the demand surface -> data/parquet/demand_surface.parquet.

The project's core insight: we have no passenger counts, but **dwell time is a
demand proxy**. A bus that sits longer at a stop boarded/alighted more people.
Aggregated over a representative period to a (stop x daytype x hour) grid, the
dwell signal becomes a stable map of how demand moves through Regensburg across
the day — the input to the flex-routing pitch (see PLAN.md).

Input: features.parquet (already filtered to door_opened rows at stop-event grain).

Method
------
1. Baseline window selection. features.parquet stitches 6 disjoint capture
   windows. For a *typical-city* surface we use only the two normal full-network
   2-week ITCS windows (Oct 2023 + Oct 2024). We DROP:
     - the Line-1 full year  -> single corridor, would swamp every other stop;
     - Christkindlmarkt / Hochwasser / UniLinien -> event/disruption snapshots
       that bias their own stops. (Those windows are gold for event-pulse
       stories later — handled separately, not in the baseline surface.)
   Both baseline windows are October with the universities in session, so the
   surface consistently reflects term-time demand.

2. Demand proxy = boarding-driven dwell. We keep only dwell that plausibly
   reflects boarding/alighting, using the cleaning proven in notebook
   07_dwell_demand (without it "the demand map just lights up the depots"):
     - drop each trip's first/last stop (terminus layovers);
     - drop dwell > DWELL_CAP_S (timing-point holds where the driver waits to
       leave on time, not passenger activity) and dwell <= 0;
     - drop |delay_arr_s| >= DELAY_CAP_S (broken/garbage records).

3. Time buckets. Each stop-event is bucketed by its arrival-at-door hour
   (coalesced to departure / planned) into hour 0-23 and a daytype:
   weekday / sat / sun, with public holidays folded into 'sun'. Transit demand
   patterns differ mainly along these axes.

4. Normalisation. Raw dwell sums depend on how many days each window sampled, so
   we divide by the number of distinct operating days per daytype -> a
   *per-typical-day* figure. demand_proxy is then that figure min-max scaled to
   [0, 1] across all cells for heatmap colouring.

Output grain: one row per (stop_code, daytype, hour) with coords + raw and
normalised demand columns.

Idempotent: skips if demand_surface.parquet exists (use --force to rebuild).

Usage:
    uv run python pipeline/build_demand.py
    uv run python pipeline/build_demand.py --force
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

OUT_DIR = Path("data/parquet")
FEATURES = OUT_DIR / "features.parquet"
OUT = OUT_DIR / "demand_surface.parquet"

# The two normal full-network capture windows (source_window == parquet stem).
BASELINE_WINDOWS = [
    "08.10.2023_21.10.2023_ITCS",
    "06.10.2024_19.10.2024_ITCS",
]

DWELL_CAP_S = 120  # drop timing-point holds above this; boarding dwell sits well below
DELAY_CAP_S = 7200  # drop records with |arrival delay| >= 2h as broken


def build() -> pl.DataFrame:
    lf = pl.scan_parquet(FEATURES).filter(
        pl.col("source_window").is_in(BASELINE_WINDOWS)
        & (pl.col("dwell_s") > 0)
        & (pl.col("dwell_s") <= DWELL_CAP_S)
        & (pl.col("delay_arr_s").abs() < DELAY_CAP_S)
        & pl.col("stop_lat").is_not_null()
    )

    # Drop each trip's first/last stop — those are terminus layovers, not boarding.
    # `is_terminus` is pre-computed in assemble.py on the full cleansed trip (before
    # the dwell/door filters above), so it marks the trip's true endpoints. Computing
    # min/max here instead would relabel whatever interior stop happens to survive as
    # the first/last row and wrongly drop it.
    lf = lf.filter(~pl.col("is_terminus"))

    # Bucket each event by the moment the bus is at the stop.
    event_ts = pl.coalesce(
        "ts_arrival_actual_door", "ts_departure_actual_door", "ts_arrival_planned"
    )
    daytype = (
        pl.when(pl.col("is_public_holiday"))
        .then(pl.lit("sun"))
        .when(event_ts.dt.weekday() == 6)
        .then(pl.lit("sat"))
        .when(event_ts.dt.weekday() == 7)
        .then(pl.lit("sun"))
        .otherwise(pl.lit("weekday"))
    )

    enriched = lf.with_columns(
        event_ts.dt.hour().alias("hour"),
        event_ts.dt.date().alias("_day"),
        daytype.alias("daytype"),
        pl.col("dwell_s").alias("_dwell"),
    )

    # Distinct operating days per daytype -> divisor that cancels sample size.
    days_per_type = (
        enriched.select("daytype", "_day")
        .unique()
        .group_by("daytype")
        .agg(pl.len().alias("n_days"))
    )

    cells = (
        enriched.group_by("stop_code", "daytype", "hour")
        .agg(
            pl.len().alias("n_events"),
            pl.col("_dwell").sum().alias("dwell_sum_s"),
            pl.col("_dwell").mean().alias("dwell_mean_s"),
            pl.col("_dwell").median().alias("dwell_median_s"),
            pl.col("stop_name").first().alias("stop_name"),
            pl.col("stop_lat").first().alias("stop_lat"),
            pl.col("stop_lon").first().alias("stop_lon"),
        )
        .join(days_per_type, on="daytype", how="left")
        .with_columns(
            # per-typical-day figures
            (pl.col("dwell_sum_s") / pl.col("n_days")).alias("dwell_per_day_s"),
            (pl.col("n_events") / pl.col("n_days")).alias("trips_per_day"),
        )
        .collect()
    )

    # Heatmap colour: min-max scale dwell_per_day_s across all cells.
    lo = cells["dwell_per_day_s"].min()
    hi = cells["dwell_per_day_s"].max()
    span = (hi - lo) or 1.0
    cells = cells.with_columns(
        ((pl.col("dwell_per_day_s") - lo) / span).alias("demand_proxy")
    ).sort("stop_code", "daytype", "hour")

    return cells.select(
        "stop_code", "stop_name", "stop_lat", "stop_lon",
        "daytype", "hour",
        "n_events", "trips_per_day",
        "dwell_sum_s", "dwell_mean_s", "dwell_median_s", "dwell_per_day_s",
        "demand_proxy",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the dwell-based demand surface.")
    ap.add_argument("--force", action="store_true", help="rebuild even if output exists")
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f"CACHED  {OUT} exists — use --force to rebuild")
        return

    if not FEATURES.exists():
        raise SystemExit(f"missing {FEATURES} — run assemble first")

    df = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)
    print(f"RAN     wrote {OUT}  ({df.height} cells, {df['stop_code'].n_unique()} stops)")


if __name__ == "__main__":
    main()
