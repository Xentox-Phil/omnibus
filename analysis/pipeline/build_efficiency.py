"""Route-efficiency + flex-bus detection (Model B — thin an over-served trunk).

Two outputs:
  data/parquet/route_efficiency.parquet  — (line, dir, daytype, hour) grid
  data/parquet/flex_candidates.parquet   — the declared flex fleet (per line, dir)

Pitch role
----------
The fixed GTFS schedule stays exactly as riders know it. On top of it we mark a
set of **flex buses** — vehicles we can pull toward an event hotspot without
breaking the timetable for anyone. The spare capacity does *not* come from
diverting a near-empty peripheral line (that line's one bus IS the service). It
comes from **thinning a high-frequency trunk**: a corridor running 5–6 buses/h
can drop one and still hold a tight headway. Frequency/redundancy is therefore
the selection signal — *routes where a lot of buses already run* — not low demand.

So this module answers two questions:
  1. "Which lines are good flex donors?"  -> flex_candidates.parquet (the fleet)
  2. "Right now (daytype, hour), which donor can spare the most?" -> recommend()

The thinning math
-----------------
A trunk keeps an acceptable headway as long as we leave ``KEEP_TRIPS`` buses an
hour on it (``ceil(60 / HEADWAY_FLOOR_MIN)``). Everything above that is spare:

    buses_freed = max(0, trips_per_hour - KEEP_TRIPS)

A line is a flex donor in an hour when ``buses_freed > 0`` *and* it actually runs
through populated stops that hour (``served_demand > 0``) — the demand check just
confirms it's a real trunk whose frequency is justified, not a scheduling quirk.
A line is published in the fleet (``flex_eligible``) when it clears that bar for
enough hours of the day (``MIN_DONOR_HOURS``).

Data lineage
------------
  stop_times.parquet  + service_days.parquet  -> trips_per_hour   (GTFS frequency)
  lines.parquet                               -> route length, stop sequence
  stops_geo.parquet                           -> DHID <-> stop_code bridge
  demand_surface.parquet                      -> dwell-demand per (stop, daytype, hour)

daytype is derived from each service date's weekday (Sat / Sun / weekday) via
service_days — robust, and GTFS already folds public holidays onto Sunday
services, matching demand_surface's holiday handling.

Key columns (route_efficiency)
------------------------------
  trips_per_hour   buses/hour this line runs in this cell (GTFS, fractional rate)
  headway_min      60 / trips_per_hour              (gap riders currently see)
  buses_freed      trips_per_hour - KEEP_TRIPS, >=0 (spare after thinning to floor)
  served_demand    sum of demand_proxy over the line's stops this cell
  demand_per_km    served_demand / route_km         (is the route in a hot area?)
  demand_per_bus   served_demand / trips_per_hour   (load per bus; context only)
  efficiency_rank  ascending demand_per_km within (daytype, hour); 1 = least efficient

Caveats (say them if asked):
  - demand_proxy at a stop is shared across every line serving it — served_demand
    is "demand in this line's catchment", not demand it uniquely carries.
  - trips_per_hour is a *per-typical-day* rate (fractional), so buses_freed is an
    expected spare, not a guaranteed whole vehicle every single day.
  - HEADWAY_FLOOR_MIN is a guess — RVV may publish a tighter service standard;
    the whole flex supply scales with it. Validate before quoting numbers.

Idempotent: skips if both outputs exist (use --force to rebuild).

Usage:
    uv run python pipeline/build_efficiency.py
    uv run python pipeline/build_efficiency.py --force
    uv run python pipeline/build_efficiency.py --recommend --daytype weekday --hour 15
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import polars as pl

OUT_DIR = Path("data/parquet")
LINES = OUT_DIR / "lines.parquet"
STOPS_GEO = OUT_DIR / "stops_geo.parquet"
DEMAND = OUT_DIR / "demand_surface.parquet"
STOP_TIMES = OUT_DIR / "stop_times.parquet"
SERVICE_DAYS = OUT_DIR / "service_days.parquet"

OUT_EFF = OUT_DIR / "route_efficiency.parquet"
OUT_FLEX = OUT_DIR / "flex_candidates.parquet"

# Model B knob: the worst headway we'll tolerate on a trunk after pulling a bus.
# GUESS — RVV may publish a tighter service standard; the entire flex supply
# scales with this. Validate before quoting buses-freed numbers.
HEADWAY_FLOOR_MIN = 20
# Buses we must leave running to hold that headway floor. ceil(60/20) = 3.
KEEP_TRIPS = math.ceil(60 / HEADWAY_FLOOR_MIN)
# A published donor must be able to spare a bus across at least this many hours
# of the day — a one-hour blip isn't a dependable flex line.
MIN_DONOR_HOURS = 3


def _frequency() -> pl.DataFrame:
    """trips_per_hour = trips on a *typical day* of each daytype.

    A single (line, dir) runs under several GTFS service patterns that all fall
    on weekdays (school-day, Ferien, special calendars). Summing their trip
    definitions would count ~4 timetables as one day. Instead we expand each
    service to the dates it actually runs (service_days), count trip-departures
    per (daytype, hour) across all those dates, and divide by the number of
    distinct dates of that daytype — the same per-typical-day normalisation
    build_demand uses, so demand and frequency are on the same footing.
    """
    st = pl.read_parquet(STOP_TIMES)
    origins = (
        st.filter(pl.col("stop_seq") == pl.col("stop_seq").min().over("trip_id"))
        .select("trip_id", "line_id", "direction_id", "service_id", "dep_s")
        .unique("trip_id")
        .with_columns(((pl.col("dep_s") // 3600) % 24).cast(pl.Int8).alias("hour"))
    )

    sd = pl.read_parquet(SERVICE_DAYS)
    wd = pl.col("date").dt.weekday()  # 1=Mon … 7=Sun
    daytype = (
        pl.when(wd == 6).then(pl.lit("sat"))
        .when(wd == 7).then(pl.lit("sun"))
        .otherwise(pl.lit("weekday"))
    )
    date_svc = sd.with_columns(daytype.alias("daytype"))
    n_dates = (
        date_svc.select("date", "daytype").unique()
        .group_by("daytype").agg(pl.len().alias("n_dates"))
    )
    # how many dates of each daytype each service actually runs
    svc_dates = date_svc.group_by("service_id", "daytype").agg(pl.len().alias("svc_dates"))

    return (
        origins.join(svc_dates, on="service_id", how="inner")
        .group_by("line_id", "direction_id", "daytype", "hour")
        .agg(pl.col("svc_dates").sum().alias("trip_departures"))
        .join(n_dates, on="daytype", how="left")
        .with_columns((pl.col("trip_departures") / pl.col("n_dates")).alias("trips_per_hour"))
        .select("line_id", "direction_id", "daytype", "hour", "trips_per_hour")
    )


def _served_demand() -> pl.DataFrame:
    """Sum of demand_proxy over each line's stops per (daytype, hour)."""
    lines = pl.read_parquet(LINES).select("line_id", "direction_id", "stop_sequence")
    bridge = (
        pl.read_parquet(STOPS_GEO)
        .filter(pl.col("dhid").is_not_null())
        .select("dhid", "stop_code")
        .unique(subset="dhid")
    )
    demand = pl.read_parquet(DEMAND).select("stop_code", "daytype", "hour", "demand_proxy")
    line_stops = (
        lines.explode("stop_sequence")
        .rename({"stop_sequence": "dhid"})
        .join(bridge, on="dhid", how="left")
        .filter(pl.col("stop_code").is_not_null())
        .select("line_id", "direction_id", "stop_code")
    )
    return (
        line_stops.join(demand, on="stop_code", how="inner")
        .group_by("line_id", "direction_id", "daytype", "hour")
        .agg(
            pl.col("demand_proxy").sum().alias("served_demand"),
            pl.col("stop_code").n_unique().alias("n_stops_matched"),
        )
    )


def build_efficiency() -> pl.DataFrame:
    geom = pl.read_parquet(LINES).select(
        "line_id", "direction_id",
        pl.col("stop_sequence").list.len().alias("n_stops"),
        (pl.col("length_m") / 1000).alias("length_km"),
    )
    # GTFS frequency is the backbone for *when a bus runs*; the inner join on
    # geometry restricts to the demand-era network we can map and route. GTFS-only
    # lines (night N*, regional 5/70/78/80, B/D, festival) had no demand sampled in
    # the Oct windows — keeping them would misread "no data" as "empty bus".
    grid = (
        _frequency()
        .join(_served_demand(), on=["line_id", "direction_id", "daytype", "hour"], how="left")
        .join(geom, on=["line_id", "direction_id"], how="inner")
        .with_columns(
            pl.col("served_demand").fill_null(0.0),
            pl.col("n_stops_matched").fill_null(0),
        )
        .with_columns(
            (60 / pl.col("trips_per_hour")).alias("headway_min"),
            (pl.col("trips_per_hour") - KEEP_TRIPS).clip(lower_bound=0).alias("buses_freed"),
            (pl.col("served_demand") / pl.col("length_km")).alias("demand_per_km"),
            (pl.col("served_demand") / pl.col("trips_per_hour")).alias("demand_per_bus"),
        )
        .with_columns(
            pl.col("demand_per_km").rank("ordinal").over("daytype", "hour").alias("efficiency_rank")
        )
        .sort("daytype", "hour", "buses_freed", descending=[False, False, True])
    )
    return grid.select(
        "line_id", "direction_id", "daytype", "hour",
        "trips_per_hour", "headway_min", "buses_freed",
        "n_stops", "n_stops_matched", "length_km",
        "served_demand", "demand_per_km", "demand_per_bus", "efficiency_rank",
    )


def build_flex(eff: pl.DataFrame) -> pl.DataFrame:
    """The flex fleet (Model B): high-frequency trunks that can spare a bus while
    holding the headway floor. One row per (line, direction).

    A donor hour is one where the line could give up a bus (buses_freed > 0) and
    provably runs through populated stops (served_demand > 0 — confirms a real,
    demand-justified trunk, not a scheduling artefact). A line is published in the
    fleet when it clears that bar for >= MIN_DONOR_HOURS hours of the day.
    Selection is pure frequency/redundancy: demand is a sanity check, never a
    low-demand ranking — that was the Model-A mistake this replaces.
    """
    donor_hours = eff.filter((pl.col("buses_freed") > 0) & (pl.col("served_demand") > 0))
    per_line = (
        donor_hours.group_by("line_id", "direction_id")
        .agg(
            pl.len().alias("donor_hours"),
            pl.col("trips_per_hour").mean().alias("mean_trips_per_hour"),
            pl.col("trips_per_hour").max().alias("peak_trips_per_hour"),
            pl.col("buses_freed").sum().alias("total_buses_freed"),
            pl.col("buses_freed").max().alias("peak_buses_freed"),
            pl.col("demand_per_bus").median().alias("median_demand_per_bus"),
            pl.col("demand_per_km").median().alias("median_demand_per_km"),
        )
    )
    return (
        per_line.with_columns(
            (pl.col("donor_hours") >= MIN_DONOR_HOURS).alias("flex_eligible")
        )
        # strongest, most dependable trunks first
        .sort(["flex_eligible", "total_buses_freed"], descending=[True, True])
    )


def recommend(daytype: str, hour: int, n: int = 5) -> pl.DataFrame:
    """Of the *declared* flex fleet, which donors can spare the most right now?

    Two-step by design: a line is published as a flex bus in flex_candidates
    (riders/operators know it up front); this selector only ever picks from that
    fleet. It keeps the donors that can actually spare a bus this hour
    (buses_freed > 0, with measured demand) and ranks them by how many buses they
    free — the top one thins the most without breaking its headway floor.
    """
    eff = pl.read_parquet(OUT_EFF) if OUT_EFF.exists() else build_efficiency()
    flex = pl.read_parquet(OUT_FLEX) if OUT_FLEX.exists() else build_flex(eff)
    fleet = flex.filter(pl.col("flex_eligible")).select("line_id", "direction_id")
    return (
        eff.join(fleet, on=["line_id", "direction_id"], how="inner")  # declared flex buses only
        .filter(
            (pl.col("daytype") == daytype)
            & (pl.col("hour") == hour)
            & (pl.col("buses_freed") > 0)
            & (pl.col("served_demand") > 0)
        )
        .sort("buses_freed", descending=True)
        .head(n)
        .select("line_id", "direction_id", "trips_per_hour", "headway_min",
                "buses_freed", "served_demand", "demand_per_bus", "demand_per_km")
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Route efficiency + flex-bus detection (Model B).")
    ap.add_argument("--force", action="store_true", help="rebuild even if outputs exist")
    ap.add_argument("--recommend", action="store_true", help="print flex picks for a moment")
    ap.add_argument("--daytype", default="weekday", choices=["weekday", "sat", "sun"])
    ap.add_argument("--hour", type=int, default=15)
    args = ap.parse_args()

    if args.recommend:
        with pl.Config(tbl_rows=20):
            print(f"Flex picks — {args.daytype} {args.hour:02d}:00 (most spare first, "
                  f"thin to <= {HEADWAY_FLOOR_MIN}-min headway)")
            print(recommend(args.daytype, args.hour))
        return

    if OUT_EFF.exists() and OUT_FLEX.exists() and not args.force:
        print(f"CACHED  {OUT_EFF.name} + {OUT_FLEX.name} exist — use --force to rebuild")
        return

    for p in (LINES, STOPS_GEO, DEMAND, STOP_TIMES, SERVICE_DAYS):
        if not p.exists():
            raise SystemExit(f"missing {p} — build it first")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    eff = build_efficiency()
    eff.write_parquet(OUT_EFF)
    flex = build_flex(eff)
    flex.write_parquet(OUT_FLEX)
    print(f"RAN     {OUT_EFF.name}  ({eff.height} cells, {eff['line_id'].n_unique()} lines)")
    print(f"RAN     {OUT_FLEX.name} ({flex.height} line-dirs, "
          f"{flex['flex_eligible'].sum()} flex-eligible, keep={KEEP_TRIPS} buses/h)")


if __name__ == "__main__":
    main()
