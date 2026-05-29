"""GTFS stop coordinates for the RVV network.

Two-tier architecture (mirrors the events/strikes CSV pattern):

  data/raw/gtfs/regensburg_stops.parquet     COMMITTED raw snapshot — ~4k GTFS
                                              stops inside the RVV bbox
                                              (Regensburg city + Landkreis).
                                              Built once from the gtfs.de
                                              Germany feed (245 MB), then kept
                                              in-repo so teammates never have to
                                              re-download.

  data/parquet/stops_geo.parquet             DERIVED — our ~325 RVV stop_names
                                              joined to coordinates. Gitignored,
                                              regenerable in <1s from the raw
                                              snapshot + RVV window parquets.

Default invocation: reads the committed raw snapshot, rebuilds stops_geo.
That's the path teammates take after `git clone`.

Refreshing the raw snapshot (only needed if RVV adds/moves stops in the GTFS
feed — extremely rare): pass `--refresh-raw` to re-download the 245 MB zip,
re-extract, re-filter, and overwrite `regensburg_stops.parquet`. Commit the
result if it changes meaningfully.

Source: gtfs.de Germany free aggregator → https://download.gtfs.de/germany/free/latest.zip
Full doc: docs/GTFS.md (coverage stats, outliers, future-work checklist).
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

import polars as pl

GTFS_URL = "https://download.gtfs.de/germany/free/latest.zip"

RAW_DIR = Path("data/raw/gtfs")
RAW_SNAPSHOT = RAW_DIR / "regensburg_stops.parquet"
ZIP_PATH = RAW_DIR / "germany_free.zip"
STOPS_TXT = RAW_DIR / "stops.txt"

OUT_DIR = Path("data/parquet")
OUT_GEO = OUT_DIR / "stops_geo.parquet"

# Regensburg city + Landkreis bbox — wide enough for rural RVV lines.
BBOX = {"lat_min": 48.85, "lat_max": 49.20, "lon_min": 11.85, "lon_max": 12.45}

CONTEXT_FILES = {
    "weather_regensburg.parquet", "daylight_regensburg.parquet",
    "holidays_bavaria.parquet", "university_calendar.parquet",
    "events_regensburg.parquet", "strikes_rvv.parquet",
    "stops_geo.parquet", "features.parquet",
}


def rvv_stop_names() -> pl.DataFrame:
    """stop_name + event count from every RVV window parquet."""
    paths = sorted(p for p in OUT_DIR.glob("*.parquet") if p.name not in CONTEXT_FILES)
    if not paths:
        raise SystemExit(f"no RVV window parquets in {OUT_DIR} — run ingest first.")
    df = pl.concat(
        [pl.scan_parquet(p).select("stop_name") for p in paths],
        how="diagonal_relaxed",
    ).collect()
    return (
        df.filter(pl.col("stop_name").is_not_null())
        .group_by("stop_name").len()
        .rename({"len": "event_count"})
    )


def _refresh_raw_snapshot() -> pl.DataFrame:
    """Re-download → extract → bbox-filter → overwrite the committed raw snapshot."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] {GTFS_URL}  (~245 MB, one-time)")
    urllib.request.urlretrieve(GTFS_URL, ZIP_PATH)
    print(f"[ok] {ZIP_PATH.stat().st_size / 1e6:.0f} MB")

    print("[extract] stops.txt")
    with zipfile.ZipFile(ZIP_PATH) as z, STOPS_TXT.open("wb") as f:
        f.write(z.read("stops.txt"))

    bbox = (
        pl.read_csv(STOPS_TXT, infer_schema_length=10_000)
        .filter(
            pl.col("stop_lat").is_between(BBOX["lat_min"], BBOX["lat_max"])
            & pl.col("stop_lon").is_between(BBOX["lon_min"], BBOX["lon_max"])
        )
        .select("stop_id", "stop_name", "stop_lat", "stop_lon", "parent_station")
        .unique(subset=["stop_id"])
        .sort("stop_name")
    )
    print(f"[bbox] {bbox.height:,} stops in RVV bbox")
    bbox.write_parquet(RAW_SNAPSHOT, compression="zstd")
    print(f"[ok] wrote {RAW_SNAPSHOT} ({RAW_SNAPSHOT.stat().st_size/1024:.0f} KB) — commit if changed")

    # Clean up download artefacts so we don't leave 280 MB lying around.
    ZIP_PATH.unlink(missing_ok=True)
    STOPS_TXT.unlink(missing_ok=True)
    return bbox


def _normalise(c: str) -> pl.Expr:
    return (
        pl.col(c).str.to_lowercase()
        .str.replace_all("ß", "ss")
        .str.replace_all("ü", "u")
        .str.replace_all("ö", "o")
        .str.replace_all("ä", "a")
    )


def _looks_like_depot_code(name: str | None) -> bool:
    """Skip fuzzy match for operator/depot codes (all-caps short, special tags)."""
    if not name or not name.strip():
        return True
    n = name.strip()
    if n.replace(" ", "").isupper() and len(n.replace(" ", "")) <= 4:
        return True
    if any(t in n for t in (" BTH", " DTH", " MTH", "Testhaltestelle", "Kein Zustieg", "vor LSt")):
        return True
    return False


def _build_geo(bbox: pl.DataFrame) -> pl.DataFrame:
    ours = rvv_stop_names()
    total = ours["event_count"].sum()
    print(f"[rvv] {ours.height} unique stop_names, {total:,} total stop-events")

    gtfs_unique = bbox.select("stop_name", "stop_lat", "stop_lon").unique(subset=["stop_name"])

    exact = ours.join(gtfs_unique, on="stop_name", how="left")
    n_exact = exact.filter(pl.col("stop_lat").is_not_null()).height
    print(f"[match] exact-name: {n_exact}/{ours.height} ({n_exact/ours.height*100:.1f}%)")

    misses = exact.filter(pl.col("stop_lat").is_null()).select("stop_name", "event_count")
    candidates = misses.filter(
        ~pl.col("stop_name").map_elements(_looks_like_depot_code, return_dtype=pl.Boolean)
    )

    gtfs_norm = gtfs_unique.with_columns(_normalise("stop_name").alias("_gnorm")).rename(
        {"stop_name": "_gtfs_name"}
    )
    miss_norm = candidates.with_columns(_normalise("stop_name").alias("_onorm"))

    fuzzy = (
        miss_norm.join(gtfs_norm, how="cross")
        .filter(pl.col("_gnorm").str.contains(pl.col("_onorm"), literal=True))
        .with_columns(_match_len=pl.col("_gtfs_name").str.len_chars())
        .sort("stop_name", "_match_len")
        .group_by("stop_name").first()
        .select("stop_name", "stop_lat", "stop_lon", pl.col("_gtfs_name").alias("matched_to"))
    )

    print(f"[fuzzy] added: {fuzzy.height}")
    for r in fuzzy.iter_rows(named=True):
        print(f"        {r['stop_name']!r:<32} ← {r['matched_to']!r}")

    final = (
        exact.join(fuzzy.select("stop_name", "stop_lat", "stop_lon"),
                   on="stop_name", how="left", suffix="_fz")
        .with_columns(
            stop_lat=pl.coalesce(["stop_lat", "stop_lat_fz"]),
            stop_lon=pl.coalesce(["stop_lon", "stop_lon_fz"]),
        )
        .drop("stop_lat_fz", "stop_lon_fz")
    )
    matched = final.filter(pl.col("stop_lat").is_not_null())
    covered = matched["event_count"].sum()
    print(
        f"[final] {matched.height}/{ours.height} stops ({matched.height/ours.height*100:.1f}%) "
        f"covering {covered:,}/{total:,} events ({covered/total*100:.2f}%)"
    )
    n_miss = ours.height - matched.height
    if n_miss:
        print(f"[misses] {n_miss} unmatched — see docs/GTFS.md for the list")
    return matched.sort("event_count", descending=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="rebuild stops_geo.parquet even if it exists")
    ap.add_argument("--refresh-raw", action="store_true",
                    help="re-download the 245 MB GTFS zip + rebuild regensburg_stops.parquet")
    args = ap.parse_args()

    if OUT_GEO.exists() and not args.force and not args.refresh_raw:
        print(f"[skip] {OUT_GEO} exists. --force to rebuild, --refresh-raw to also re-fetch GTFS.")
        return 0

    if args.refresh_raw or not RAW_SNAPSHOT.exists():
        if not args.refresh_raw:
            print(f"[note] {RAW_SNAPSHOT} missing — will download. (It's committed; usually present.)")
        bbox = _refresh_raw_snapshot()
    else:
        bbox = pl.read_parquet(RAW_SNAPSHOT)
        print(f"[raw] {bbox.height:,} stops from {RAW_SNAPSHOT} (committed snapshot)")

    geo = _build_geo(bbox)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    geo.write_parquet(OUT_GEO, compression="zstd")
    print(f"[ok] {OUT_GEO}  ({geo.height} stops, {OUT_GEO.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
