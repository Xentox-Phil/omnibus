"""Step 2a — cut the July feed down to a small demo GTFS zip.

  uv run python pipeline/sumo/subset_gtfs.py [--force]

Keeps only the lines connecting HBF and Jahnstadion (3, 5 serve the stadium;
1 is the flagship corridor; X4 the express) and only trips that overlap the
match window. gtfs2pt's --date then handles calendar filtering. Output is a
zip gtfs2pt can read directly. UTF-8 (GTFS is always UTF-8; the UTF-16 quirk
is the RVV operational CSVs, not this feed).
"""

from __future__ import annotations

import argparse
import zipfile

import polars as pl

import _sumo_env as env

LINES = {"1", "3", "5", "X4"}
DATE = "20250728"
# match window 16:00-21:00, in GTFS seconds-since-midnight
WIN_START, WIN_END = 16 * 3600, 21 * 3600

# files copied verbatim (filtered ones are written explicitly below)
PASSTHROUGH = ["agency.txt", "feed_info.txt"]


def gtfs_seconds(col: str) -> pl.Expr:
    """HH:MM:SS (HH may exceed 24) -> seconds since service midnight."""
    parts = pl.col(col).str.split(":")
    return (
        parts.list.get(0).cast(pl.Int32) * 3600
        + parts.list.get(1).cast(pl.Int32) * 60
        + parts.list.get(2).cast(pl.Int32)
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    src = env.GTFS_JULY
    out_zip = env.DATA_DIR / f"gtfs_subset_{DATE}.zip"
    env.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if out_zip.exists() and not args.force:
        print(f"subset exists: {out_zip} (use --force)")
        return

    routes = pl.read_csv(src / "routes.txt", infer_schema_length=0)
    routes = routes.filter(pl.col("route_short_name").is_in(LINES))
    route_ids = set(routes["route_id"])
    print(f"routes kept: {sorted(route_ids)}")

    trips = pl.read_csv(src / "trips.txt", infer_schema_length=0)
    trips = trips.filter(pl.col("route_id").is_in(route_ids))

    st = pl.read_csv(src / "stop_times.txt", infer_schema_length=0)
    st = st.filter(pl.col("trip_id").is_in(set(trips["trip_id"])))
    st = st.with_columns(_sec=gtfs_seconds("departure_time"))

    # keep whole trips that have at least one stop inside the window
    in_win = (
        st.group_by("trip_id")
        .agg(pl.col("_sec").min().alias("lo"), pl.col("_sec").max().alias("hi"))
        .filter((pl.col("hi") >= WIN_START) & (pl.col("lo") <= WIN_END))
    )
    keep_trips = set(in_win["trip_id"])
    st = st.filter(pl.col("trip_id").is_in(keep_trips)).drop("_sec")
    trips = trips.filter(pl.col("trip_id").is_in(keep_trips))
    print(f"trips in window: {len(keep_trips)}")

    stops = pl.read_csv(src / "stops.txt", infer_schema_length=0)
    used = set(st["stop_id"])
    parents = set(
        stops.filter(pl.col("stop_id").is_in(used))["parent_station"].drop_nulls()
    )
    stops = stops.filter(pl.col("stop_id").is_in(used | parents))
    print(f"stops kept: {len(stops)}")

    service_ids = set(trips["service_id"])
    cal = pl.read_csv(src / "calendar.txt", infer_schema_length=0).filter(
        pl.col("service_id").is_in(service_ids)
    )
    cal_dates = pl.read_csv(src / "calendar_dates.txt", infer_schema_length=0).filter(
        pl.col("service_id").is_in(service_ids)
    )

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in [
            ("routes.txt", routes),
            ("trips.txt", trips),
            ("stop_times.txt", st),
            ("stops.txt", stops),
            ("calendar.txt", cal),
            ("calendar_dates.txt", cal_dates),
        ]:
            z.writestr(name, df.write_csv())
        for name in PASSTHROUGH:
            z.write(src / name, name)

    print(f"\nwrote {out_zip}  ({out_zip.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
