"""Per-line bus route polylines for RVV, mined from OpenStreetMap via Overpass.

GTFS has no shapes.txt — both RVV feeds carry a 74-byte stub. This pipeline
gets the geometry the other way: by pulling the `route=bus` relations OSM
contributors have already traced for every RVV line.

What an OSM bus-route relation is:
  A `relation` of `type=route route=bus` collects the ordered ways (road
  segments) the bus drives along, plus its stops/platforms. It carries tags:
  `ref` (line number, e.g. "1", "C2", "N3"), `from` / `to` (direction
  endpoints), `network` / `operator`. Each direction is a *separate* relation
  in the modern public_transport:version=2 scheme, often plus variants for
  school-day / late-evening etc.

Strategy:
  1. ONE Overpass query, bbox around Regensburg, `out geom;` so every member
     way arrives with inline lat/lon polyline.
  2. Filter to relations whose `network` contains "RVV"/"Regensburger
     Verkehrsverbund" — drops Flixbus + neighbouring Verbund routes that
     happen to cross the bbox.
  3. Stitch member ways in declared order, flipping each segment if its
     endpoint doesn't connect to the previous — that's all the standard
     OSM route stitching needs (members are usually well-ordered).
  4. Write one row per relation: ref / from / to / GeoJSON LineString /
     n_ways / n_points / length_m. No collapsing to a single "canonical"
     row per line — variants are real (school runs, festival diversions)
     and the consumer picks.

Output (gitignored, ~5 MB):
  data/parquet/routes_osm.parquet

Raw cache (gitignored, ~35 MB — keeps Overpass off the critical path on rerun):
  data/raw/osm/bus_routes.json

Usage:
  uv run python pipeline/fetch_routes_osm.py            # build if missing
  uv run python pipeline/fetch_routes_osm.py --force    # refetch from Overpass
  uv run python pipeline/fetch_routes_osm.py --refresh-raw  # only refetch JSON, skip parquet

Companion: fetch_routes_osrm.py reconstructs the same geometry from GTFS
stop sequences via routing, so we can measure how often each method succeeds.
See docs/ROUTES.md for the comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import polars as pl

# Regensburg bbox — wide enough to catch regional lines that touch the city.
# (south, west, north, east) — Overpass takes (s,w,n,e).
BBOX = (48.93, 11.95, 49.10, 12.25)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "omnibus-hackaburg/0.1 (Regensburg public transit analysis)"

RAW_DIR = Path("data/raw/osm")
RAW_JSON = RAW_DIR / "bus_routes.json"
OUT = Path("data/parquet/routes_osm.parquet")

# Network tag substrings that mark a relation as RVV-relevant. Operator/network
# fields are semicolon-joined when multiple Verbund/operators co-own a line.
RVV_NETWORK_KEYS = ("RVV", "Regensburger Verkehrsverbund")


# ---------------------------------------------------------------- fetch

def overpass_query() -> str:
    s, w, n, e = BBOX
    # `out geom;` inlines way-member node coords so we don't need a second pass.
    return (
        f"[out:json][timeout:180];"
        f'(relation["type"="route"]["route"="bus"]({s},{w},{n},{e}););'
        f"out geom;"
    )


def fetch_raw() -> dict:
    """POST the Overpass query, save and return the JSON."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    body = urllib.parse.urlencode({"data": overpass_query()}).encode()
    req = urllib.request.Request(
        OVERPASS_URL, data=body,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    print(f"[overpass] POST {OVERPASS_URL}  bbox={BBOX}")
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read()
    print(f"[overpass] received {len(raw)/1024/1024:.1f} MB")
    RAW_JSON.write_bytes(raw)
    return json.loads(raw)


def load_raw(force: bool) -> dict:
    if RAW_JSON.exists() and not force:
        print(f"[cache] {RAW_JSON} ({RAW_JSON.stat().st_size/1024/1024:.1f} MB)")
        return json.loads(RAW_JSON.read_bytes())
    return fetch_raw()


# ---------------------------------------------------------------- stitch

def _is_rvv(tags: dict) -> bool:
    blob = (tags.get("network", "") + ";" + tags.get("operator", "")).lower()
    return any(k.lower() in blob for k in RVV_NETWORK_KEYS)


def _flip_if_needed(prev_end: tuple[float, float] | None,
                    seg: list[dict]) -> list[dict]:
    """Return seg, possibly reversed, so it connects to prev_end."""
    if prev_end is None or not seg:
        return seg
    start = (seg[0]["lat"], seg[0]["lon"])
    end = (seg[-1]["lat"], seg[-1]["lon"])
    # Compare to both ends; flip if reversed end is closer to prev_end.
    if _dist(prev_end, end) < _dist(prev_end, start):
        return list(reversed(seg))
    return seg


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Squared planar distance — good enough for endpoint-equality voting."""
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def stitch(rel: dict) -> tuple[list[tuple[float, float]], int]:
    """Walk the relation's way members in order, flipping to keep continuity.

    Returns (polyline as list of (lat, lon), number of way segments used).
    """
    pts: list[tuple[float, float]] = []
    n_ways = 0
    for m in rel.get("members", []):
        if m.get("type") != "way":
            continue
        if m.get("role") not in ("", "forward", "backward"):
            continue  # skip 'platform' / 'stop' / 'platform_entry' ways
        geom = m.get("geometry")
        if not geom:
            continue
        n_ways += 1
        prev_end = pts[-1] if pts else None
        seg = _flip_if_needed(prev_end, geom)
        coords = [(p["lat"], p["lon"]) for p in seg]
        # Drop the duplicated joining point.
        if pts and coords and pts[-1] == coords[0]:
            coords = coords[1:]
        pts.extend(coords)
    return pts, n_ways


def polyline_length_m(pts: list[tuple[float, float]]) -> float:
    return sum(_haversine_m(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def to_geojson(pts: list[tuple[float, float]]) -> str:
    # GeoJSON is [lon, lat], not [lat, lon]. Standard footgun — flip here.
    coords = [[lon, lat] for lat, lon in pts]
    return json.dumps({"type": "LineString", "coordinates": coords}, separators=(",", ":"))


# ---------------------------------------------------------------- main

def build(raw: dict) -> pl.DataFrame:
    rels = [e for e in raw.get("elements", []) if e.get("type") == "relation"]
    print(f"[parse] {len(rels)} bus-route relations in bbox")

    rows = []
    skipped_no_geom = skipped_non_rvv = 0
    for rel in rels:
        tags = rel.get("tags", {}) or {}
        if not _is_rvv(tags):
            skipped_non_rvv += 1
            continue
        pts, n_ways = stitch(rel)
        if not pts:
            skipped_no_geom += 1
            continue
        rows.append({
            "osm_rel_id": rel["id"],
            "line": tags.get("ref", ""),
            "from_": tags.get("from", ""),
            "to_": tags.get("to", ""),
            "name": tags.get("name", ""),
            "network": tags.get("network", ""),
            "operator": tags.get("operator", ""),
            "colour": tags.get("colour", ""),
            "n_ways": n_ways,
            "n_points": len(pts),
            "length_m": round(polyline_length_m(pts), 1),
            "geometry": to_geojson(pts),
        })

    print(f"[filter] kept {len(rows)} RVV relations "
          f"(dropped {skipped_non_rvv} non-RVV, {skipped_no_geom} empty)")
    df = pl.DataFrame(rows).sort(["line", "from_", "to_"])
    return df


def summary(df: pl.DataFrame) -> None:
    n_lines = df["line"].n_unique()
    total_km = df["length_m"].sum() / 1000
    print(f"[ok]   {df.height} relations across {n_lines} unique line refs, "
          f"{total_km:,.0f} km total polyline")
    # Coverage by line — show top 20.
    per_line = (
        df.group_by("line")
        .agg(pl.len().alias("n_variants"),
             pl.col("length_m").mean().alias("avg_len_m"))
        .sort("n_variants", descending=True)
    )
    print(f"[lines top 15 by variant count]")
    for r in per_line.head(15).iter_rows(named=True):
        print(f"  {r['line']:<8} {r['n_variants']:>3} variants  "
              f"avg {r['avg_len_m']/1000:.1f} km")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="refetch from Overpass even if cached JSON exists")
    ap.add_argument("--refresh-raw", action="store_true",
                    help="refetch JSON only, don't rebuild parquet")
    args = ap.parse_args()

    if args.refresh_raw:
        fetch_raw()
        return 0

    if OUT.exists() and not args.force:
        print(f"[skip] {OUT} exists. --force to rebuild.")
        return 0

    raw = load_raw(args.force)
    df = build(raw)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT, compression="zstd")
    print(f"[write] {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    summary(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
