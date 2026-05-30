"""GTFS stop coordinates + route descriptions for the RVV network.

RVV-native pipeline. Joins our stop-event data to coordinates through RVV's own
master data instead of fuzzy-matching names against the nationwide gtfs.de feed:

    stop_event.stop_code  →  Haltestellen master CSV (Kürzel → DHID)
                          →  RVV GTFS stops.txt (DHID → lat/lon)

`stop_code` is a clean operator key (HBF, AKORN, BPLZ, …), so the join is
deterministic — no name normalisation, no fuzzy false-positives, no 245 MB
download. 315/324 codes carry a master DHID; the 9 that don't are depot /
subcontractor / test markers (documented in docs/CONTACT_NOTES.md), correctly
left without a coordinate.

Inputs (all committed, tiny):
  data/raw/Haltestellen und -punkte - Haltestelle.csv   stop master (Kürzel→DHID)
  data/raw/gtfs_july2025/stops.txt                      RVV city feed (coords)
  data/raw/gtfs_july2025/routes.txt                     line → route_long_name
  data/raw/gtfs_aug2025/stops.txt                       region feed (extra coords)

Output (gitignored, regenerable in <1s):
  data/parquet/stops_geo.parquet    one row per stop_code: name, dhid, lat, lon, kind

Note: route_long_name is NOT sourced here. July's city feed leaves it empty and
Aug's descriptions are keyed to regional line IDs that don't match our `line`
column (only 2/47 lines join). Route descriptions live in Linien_Erklärung.pdf —
a separate extraction (see docs/RAW_INPUTS.md).

Usage:
  uv run python pipeline/fetch_gtfs.py            # build (skip if present)
  uv run python pipeline/fetch_gtfs.py --force    # rebuild
  uv run python pipeline/fetch_gtfs.py --compare  # old gtfs.de vs new coverage

Full doc: docs/GTFS.md. Code glossary: docs/CONTACT_NOTES.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import polars as pl

RAW = Path("data/raw")
MASTER_CSV = RAW / "Haltestellen und -punkte - Haltestelle.csv"
# Feed precedence: july is the RVV *city* feed (286 de:09362 stops). aug is
# region-wide — used only to backfill coords july lacks. july coords win on
# conflict.
GTFS_FEEDS = [RAW / "gtfs_july2025", RAW / "gtfs_aug2025"]

OUT_DIR = Path("data/parquet")
OUT_GEO = OUT_DIR / "stops_geo.parquet"

# Legacy gtfs.de bbox snapshot — only read by --compare now.
OLD_SNAPSHOT = RAW / "gtfs" / "regensburg_stops.parquet"

# A stop-event window is identified by its schema (raw event timestamps + stop
# identity), not a denylist — robust to new context tables landing alongside.
WINDOW_SIGNATURE = {"ts_arrival_planned", "stop_code"}
SELF_OUTPUT = {"features.parquet"}

# stop_codes with no master DHID — operational, not passenger stops. Source:
# RVV challenge contact (see docs/CONTACT_NOTES.md). kind drives the `kind`
# column so the analysis/frontend layer can filter depots out explicitly.
NON_STOP_KIND = {
    "BTH SMO": "depot_rvv",     # RVV's own depot ("bus ready to be picked up")
    "vor LSt": "depot_rvv",     # vor Leitstelle — same place as BTH SMO
    "RBO": "depot_sub",         # Regionalbus Ostbayern (subcontractor)
    "Wittl": "depot_sub",       # Wittl (subcontractor)
    "SÖLL": "depot_sub",        # Söllner (subcontractor)
    "EBEN": "depot_sub",        # Ebenbeck (subcontractor)
    "LAS": "depot_sub",         # Laschinger (subcontractor)
    "WAZ": "depot_sub",         # Watzinger (subcontractor)
    "HUK": "operational",       # operator/route code, not a stop
    "LADE": "operational",      # "Kein Zustieg" — no-boarding marker (has a DHID)
    "TEST 1": "test", "TEST 2": "test", "TEST 3": "test", "TEST 4": "test",
}

# Real stops with a DHID that neither GTFS feed carries coords for. Hand-filled
# from OSM (lat/lon of the RVV stop). ~2.8k events, ~0.08%. See docs/GTFS.md.
MANUAL_COORDS = {
    "KOEN": (49.0227, 12.1003),   # Königsstraße
    "WITE": (49.0089, 12.0731),   # Wittelsbacherstraße
}


# ---------------------------------------------------------------- inputs

def rvv_stop_codes() -> pl.DataFrame:
    """One row per stop_code from every RVV window parquet: dominant name + events."""
    paths = []
    for p in sorted(OUT_DIR.glob("*.parquet")):
        if p.name in SELF_OUTPUT:
            continue
        if WINDOW_SIGNATURE <= set(pl.scan_parquet(p).collect_schema().names()):
            paths.append(p)
    if not paths:
        raise SystemExit(f"no RVV window parquets in {OUT_DIR} — run ingest first.")
    df = pl.concat(
        [pl.scan_parquet(p).select("stop_code", "stop_name") for p in paths],
        how="diagonal_relaxed",
    ).filter(pl.col("stop_code").is_not_null()).collect()
    per = df.group_by("stop_code", "stop_name").len().rename({"len": "event_count"})
    return (
        per.sort("event_count", descending=True)
        .group_by("stop_code")
        .agg(pl.col("stop_name").first(), pl.col("event_count").sum())
    )


def master_code_to_dhid() -> dict[str, str]:
    """Kürzel → Globale Haltestellen-Kennung (DHID) from the RVV stop master."""
    rows = list(csv.reader(MASTER_CSV.open(encoding="latin-1"), delimiter=";"))
    hdr = rows[0]
    k, g = hdr.index("Kürzel"), hdr.index("Globale Haltestellen-Kennung")
    return {r[k].strip(): r[g].strip() for r in rows[1:] if r[k].strip() and r[g].strip()}


def _dhid_expr() -> pl.Expr:
    """First 3 colon-fields of a GTFS stop_id == its DHID (de:09362:11041)."""
    p = pl.col("stop_id").str.splitn(":", 5).struct
    return p.field("field_0") + ":" + p.field("field_1") + ":" + p.field("field_2")


def gtfs_dhid_coords() -> pl.DataFrame:
    """DHID → (lat, lon), platform centroid. Feeds merged in GTFS_FEEDS order."""
    frames = []
    for feed in GTFS_FEEDS:
        stops = feed / "stops.txt"
        if not stops.exists():
            continue
        g = (
            pl.read_csv(stops).filter(pl.col("stop_id").is_not_null())
            .with_columns(dhid=_dhid_expr())
            .group_by("dhid")
            .agg(stop_lat=pl.col("stop_lat").mean(), stop_lon=pl.col("stop_lon").mean())
        )
        frames.append(g)
    if not frames:
        raise SystemExit(f"no GTFS stops.txt found under {[str(f) for f in GTFS_FEEDS]}")
    # First feed wins on DHID conflict (.unique keep='first' after ordered concat).
    return pl.concat(frames).unique(subset=["dhid"], keep="first")


# ---------------------------------------------------------------- build

def build_geo() -> pl.DataFrame:
    ours = rvv_stop_codes()
    total = ours["event_count"].sum()
    print(f"[rvv] {ours.height} stop_codes, {total:,} stop-events")

    code2dhid = master_code_to_dhid()
    dhid_df = pl.DataFrame(
        {"stop_code": list(code2dhid), "dhid": list(code2dhid.values())}
    )
    coords = gtfs_dhid_coords()

    geo = (
        ours.join(dhid_df, on="stop_code", how="left")
        .join(coords, on="dhid", how="left")
    )

    # Hand-filled coords for real stops missing from both feeds.
    manual = pl.DataFrame(
        {"stop_code": list(MANUAL_COORDS),
         "m_lat": [c[0] for c in MANUAL_COORDS.values()],
         "m_lon": [c[1] for c in MANUAL_COORDS.values()]}
    )
    geo = geo.join(manual, on="stop_code", how="left").with_columns(
        stop_lat=pl.coalesce("stop_lat", "m_lat"),
        stop_lon=pl.coalesce("stop_lon", "m_lon"),
    ).drop("m_lat", "m_lon")

    # Classify: depots/tests/operational from the contact glossary, else stop.
    kind_map = pl.DataFrame(
        {"stop_code": list(NON_STOP_KIND), "kind": list(NON_STOP_KIND.values())}
    )
    geo = geo.join(kind_map, on="stop_code", how="left").with_columns(
        kind=pl.col("kind").fill_null("stop")
    )

    matched = geo.filter(pl.col("stop_lat").is_not_null())
    covered = matched["event_count"].sum()
    real = geo.filter(pl.col("kind") == "stop")
    real_matched = real.filter(pl.col("stop_lat").is_not_null())
    print(
        f"[match] {matched.height}/{ours.height} codes have coords "
        f"({covered:,}/{total:,} events, {covered/total*100:.2f}%)"
    )
    print(
        f"[real]  {real_matched.height}/{real.height} passenger stops located "
        f"({real_matched.height/real.height*100:.1f}%)"
    )
    miss_real = real.filter(pl.col("stop_lat").is_null())
    if miss_real.height:
        print(f"[gap]   {miss_real.height} real stop(s) still uncoordinated:")
        for r in miss_real.sort("event_count", descending=True).iter_rows(named=True):
            print(f"        {r['event_count']:>6,}  {r['stop_code']:<10} {r['stop_name']}")
    n_depot = geo.filter(pl.col("kind") != "stop").height
    print(f"[depot] {n_depot} non-stop codes excluded (see docs/CONTACT_NOTES.md)")
    return geo.sort("event_count", descending=True)


# ---------------------------------------------------------------- compare

def compare() -> None:
    """Old gtfs.de exact-name match vs new code→DHID→GTFS coverage."""
    ours = rvv_stop_codes()
    total = ours["event_count"].sum()

    print(f"RVV universe: {ours.height} stop_codes, {total:,} named events\n")

    if OLD_SNAPSHOT.exists():
        old_raw = pl.read_parquet(OLD_SNAPSHOT).unique(subset=["stop_name"])
        old = ours.join(
            old_raw.select("stop_name", "stop_lat", "stop_lon"),
            on="stop_name", how="left",
        )
        oh = old.filter(pl.col("stop_lat").is_not_null())
        print(f"[OLD gtfs.de name-match] {oh.height}/{ours.height} stops, "
              f"{oh['event_count'].sum():,} ev ({oh['event_count'].sum()/total*100:.2f}%)")
        old_codes = set(oh["stop_code"].to_list())
    else:
        print(f"[OLD] {OLD_SNAPSHOT} absent — skipping old side.")
        old_codes = set()

    new = build_geo()
    nh = new.filter(pl.col("stop_lat").is_not_null())
    print(f"[NEW code→DHID→GTFS]     {nh.height}/{ours.height} stops, "
          f"{nh['event_count'].sum():,} ev ({nh['event_count'].sum()/total*100:.2f}%)")
    new_codes = set(nh["stop_code"].to_list())

    if old_codes:
        gain = nh.filter(pl.col("stop_code").is_in(list(new_codes - old_codes)))
        print(f"\nboth: {len(old_codes & new_codes)} | "
              f"only-OLD: {len(old_codes - new_codes)} | only-NEW: {len(new_codes - old_codes)}")
        print("NEW gains:")
        for r in gain.sort("event_count", descending=True).iter_rows(named=True):
            print(f"  +{r['event_count']:>6,}  {r['stop_code']:<10} {r['stop_name']}")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild even if outputs exist")
    ap.add_argument("--compare", action="store_true",
                    help="print old gtfs.de vs new coverage and exit (no write)")
    args = ap.parse_args()

    if args.compare:
        compare()
        return 0

    if OUT_GEO.exists() and not args.force:
        print(f"[skip] {OUT_GEO.name} exists. --force to rebuild.")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    geo = build_geo()
    geo.write_parquet(OUT_GEO, compression="zstd")
    print(f"[ok] {OUT_GEO} ({geo.height} codes, {OUT_GEO.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
