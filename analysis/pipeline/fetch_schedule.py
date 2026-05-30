"""Unified RVV schedule + route geometry, ready for backend consumption.

Combines:
  - GTFS July city feed (trips, stop_times, calendar_dates, stops, routes)
  - routes_osm.parquet (per-line polylines from OSM, built by fetch_routes_osm.py)
  - stops_geo.parquet (stop_code -> DHID -> lat/lon, built by fetch_gtfs.py)

into three parquets designed around the backend hot path:

  data/parquet/lines.parquet         one row per (line_id, direction_id)
     line_id           str     "1", "C2", "N3"  (== GTFS route_short_name == OSM ref)
     direction_id      i8      0 / 1
     headsign          str     most common trip_headsign for this (line, dir)
     colour            str     "#75B95B"  (OSM colour tag, fallback to route_color)
     osm_rel_id        i64     which OSM variant we picked (nullable if no match)
     geometry          str     GeoJSON LineString — chosen OSM polyline
     length_m          f64     polyline length
     n_trips           i32     count of trips on this (line, dir)
     stop_sequence     list[str]   ordered DHIDs (canonical sequence — modal)
     stop_offsets_m    list[f64]   meters along polyline per stop (parallel to stop_sequence)
     stop_match_frac   f32     fraction of GTFS stops within 50m of polyline
                                (sanity score; <0.5 means the OSM match is suspect)

  data/parquet/stop_times.parquet    one row per (trip, stop)  ~361k rows
     trip_id           str
     line_id           str     (denormalised from trips)
     direction_id      i8
     service_id        str
     stop_seq          i16
     stop_id           str     DHID, normalised (no platform suffix)
     stop_name         str     denormalised — saves a join in backend
     lat, lon          f64     denormalised
     arr_s             i32     seconds since service-day midnight (handles 25:30)
     dep_s             i32

  data/parquet/service_days.parquet  one row per (date, service_id)  ~16k rows
     date              date    calendar date (parsed from GTFS YYYYMMDD)
     service_id        str

Backend startup pattern:
  lines = pl.read_parquet("lines.parquet").to_pandas()   # 94 rows, dict by (line, dir)
  stops = pl.read_parquet("stops_geo.parquet")            # 324 rows, RTree
  service_days = pl.read_parquet("service_days.parquet")  # active services per date
  stop_times = pl.read_parquet("stop_times.parquet").lazy()
      # filter to active services for the demo date, build trip_id -> [StopVisit]

Usage:
  uv run python pipeline/fetch_schedule.py            # build if missing
  uv run python pipeline/fetch_schedule.py --force    # rebuild

Prereqs:
  fetch_gtfs.py        (stops_geo.parquet)
  fetch_routes_osm.py  (routes_osm.parquet)

See docs/SCHEDULE.md for query examples and design rationale.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import Counter
from pathlib import Path

import polars as pl

RAW = Path("data/raw/gtfs_july2025")
OUT_DIR = Path("data/parquet")
OUT_LINES = OUT_DIR / "lines.parquet"
OUT_STOP_TIMES = OUT_DIR / "stop_times.parquet"
OUT_SERVICE_DAYS = OUT_DIR / "service_days.parquet"

ROUTES_OSM = OUT_DIR / "routes_osm.parquet"
STOPS_GEO = OUT_DIR / "stops_geo.parquet"
# Raw cached Overpass JSON — needed because routes_osm.parquet only carries the
# polyline, not the per-relation stop-node members. The strict validator pulls
# each candidate relation's stop members straight from here.
OSM_RAW_JSON = Path("data/raw/osm/bus_routes.json")

# Earth + Regensburg reference for the equirectangular projection used when
# computing arc-length offsets. ~30 km network — equirect is accurate to <0.1 m
# at this scale, no need for shapely/Web-Mercator.
EARTH_R = 6_371_000.0
REF_LAT = 49.013

# GTFS stop is "served" by an OSM relation if a stop-node member of that
# relation sits within this distance of the GTFS stop coord. Empirically OSM
# tags its `role='stop'` nodes at the *road* position while RVV's GTFS uses
# the platform centroid; on terminal loops the two can be 70-90 m apart
# despite being the same logical stop. 100 m tolerates that without cross-
# matching different stops (consecutive RVV stops sit ~200-300 m apart, so the
# radius can't reach a neighbouring stop).
OSM_STOP_TO_STOP_RADIUS_M = 100.0

# Strict GTFS-validation gate. A (line, direction) is only kept in lines.parquet
# if the chosen OSM relation matches GTFS this fraction of the way: each kept
# stop's nearest OSM stop-member is within OSM_STOP_TO_STOP_RADIUS_M. The
# remaining stops (typically 1-2 out of 30+) are usually OSM mapping artifacts —
# the same stop placed by different contributors at slightly different coords.
# We accept those if the *worst* miss is still under OSM_MAX_MISS_RADIUS_M;
# wrong-route candidates miss by kilometres so the cliff is unambiguous.
MIN_STOP_MATCH_FRAC = 0.90
OSM_MAX_MISS_RADIUS_M = 500.0

# Default colours for lines that don't carry one in OSM. RVV uses lime green as
# its house colour; this falls back to that until proper per-line colours land.
DEFAULT_COLOUR = "#75B95B"


# ---------------------------------------------------------------- geometry

def _latlon_to_xy(lat: float, lon: float) -> tuple[float, float]:
    """Equirectangular projection to local metres."""
    cos_ref = math.cos(math.radians(REF_LAT))
    x = EARTH_R * math.radians(lon) * cos_ref
    y = EARTH_R * math.radians(lat)
    return x, y


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres. Used for stop-to-stop comparisons."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def _project_onto_polyline(p_lat: float, p_lon: float,
                           poly: list[tuple[float, float]]) -> tuple[float, float]:
    """Project a point onto a polyline.

    Returns (arc_length_along_polyline_m, perpendicular_distance_m).
    poly is a list of (lat, lon) in order.
    """
    if len(poly) < 2:
        return 0.0, float("inf")
    px, py = _latlon_to_xy(p_lat, p_lon)
    best_d2 = float("inf")
    best_off = 0.0
    cum = 0.0
    for i in range(len(poly) - 1):
        ax, ay = _latlon_to_xy(*poly[i])
        bx, by = _latlon_to_xy(*poly[i + 1])
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        if seg2 == 0.0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        qx, qy = ax + t * dx, ay + t * dy
        d2 = (px - qx) ** 2 + (py - qy) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_off = cum + t * math.sqrt(seg2)
        cum += math.sqrt(seg2)
    return best_off, math.sqrt(best_d2)


def _parse_geojson_linestring(s: str) -> list[tuple[float, float]]:
    """GeoJSON [lon, lat] -> our (lat, lon)."""
    gj = json.loads(s)
    return [(lat, lon) for lon, lat in gj["coordinates"]]


# ---------------------------------------------------------------- GTFS load

def _dhid_from_stop_id(col: str) -> pl.Expr:
    """First three colon-fields of a GTFS stop_id are its DHID (de:09362:11041)."""
    p = pl.col(col).str.splitn(":", 5).struct
    return p.field("field_0") + ":" + p.field("field_1") + ":" + p.field("field_2")


def _parse_gtfs_time(col: str) -> pl.Expr:
    """'25:30:00' -> 91800 seconds. Handles >24h cleanly."""
    parts = pl.col(col).str.splitn(":", 3).struct
    return (
        parts.field("field_0").cast(pl.Int32) * 3600
        + parts.field("field_1").cast(pl.Int32) * 60
        + parts.field("field_2").cast(pl.Int32)
    )


def load_gtfs() -> dict[str, pl.DataFrame]:
    """Read the July city feed into typed polars frames."""
    s_str = pl.Utf8
    routes = pl.read_csv(
        RAW / "routes.txt",
        schema_overrides={"route_id": s_str, "route_short_name": s_str,
                          "route_color": s_str, "route_text_color": s_str},
    )
    trips = pl.read_csv(
        RAW / "trips.txt",
        schema_overrides={"route_id": s_str, "service_id": s_str, "trip_id": s_str,
                          "shape_id": s_str, "trip_short_name": s_str,
                          "trip_headsign": s_str, "block_id": s_str},
    )
    stop_times = pl.read_csv(
        RAW / "stop_times.txt",
        schema_overrides={"trip_id": s_str, "stop_id": s_str, "stop_headsign": s_str,
                          "arrival_time": s_str, "departure_time": s_str,
                          "shape_dist_traveled": s_str},
    )
    stops = pl.read_csv(
        RAW / "stops.txt",
        schema_overrides={"stop_id": s_str, "stop_code": s_str, "stop_name": s_str,
                          "zone_id": s_str, "parent_station": s_str,
                          "stop_desc": s_str, "stop_url": s_str,
                          "stop_timezone": s_str},
    )
    cal_dates = pl.read_csv(
        RAW / "calendar_dates.txt",
        schema_overrides={"service_id": s_str},
    )
    print(f"[gtfs] routes={routes.height} trips={trips.height} "
          f"stop_times={stop_times.height} stops={stops.height} "
          f"cal_dates={cal_dates.height}")
    return {"routes": routes, "trips": trips, "stop_times": stop_times,
            "stops": stops, "cal_dates": cal_dates}


# ---------------------------------------------------------------- service days

def build_service_days(cal_dates: pl.DataFrame) -> pl.DataFrame:
    """One row per (date, service_id) where the service is active.

    The July feed uses calendar_dates exclusively (calendar.txt's weekday flags
    are all zero) so this is a straight projection.
    """
    return (
        cal_dates.filter(pl.col("exception_type") == 1)
        .select(
            date=pl.col("date").cast(pl.Utf8).str.strptime(pl.Date, "%Y%m%d"),
            service_id=pl.col("service_id"),
        )
        .sort("date", "service_id")
    )


# ---------------------------------------------------------------- stop_times

def build_stop_times(g: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (trip, stop) with denormalised stop name + coords + line + dir."""
    stops = g["stops"].select(
        stop_id=pl.col("stop_id"),
        stop_name=pl.col("stop_name"),
        lat=pl.col("stop_lat"),
        lon=pl.col("stop_lon"),
        dhid=_dhid_from_stop_id("stop_id"),
    )
    trips = g["trips"].select(
        trip_id=pl.col("trip_id"),
        line_id=pl.col("route_id"),
        direction_id=pl.col("direction_id").cast(pl.Int8),
        service_id=pl.col("service_id"),
    )

    return (
        g["stop_times"]
        .select(
            trip_id=pl.col("trip_id"),
            stop_seq=pl.col("stop_sequence").cast(pl.Int16),
            raw_stop_id=pl.col("stop_id"),
            arr_s=_parse_gtfs_time("arrival_time"),
            dep_s=_parse_gtfs_time("departure_time"),
        )
        .join(trips, on="trip_id", how="inner")
        .join(stops.rename({"stop_id": "raw_stop_id"}),
              on="raw_stop_id", how="left")
        .select(
            "trip_id", "line_id", "direction_id", "service_id",
            "stop_seq",
            stop_id=pl.col("dhid"),
            stop_name=pl.col("stop_name"),
            lat=pl.col("lat"),
            lon=pl.col("lon"),
            arr_s=pl.col("arr_s").cast(pl.Int32),
            dep_s=pl.col("dep_s").cast(pl.Int32),
        )
        .sort("line_id", "direction_id", "trip_id", "stop_seq")
    )


# ---------------------------------------------------------------- canonical seq

def canonical_stop_sequence(stop_times: pl.DataFrame,
                            line_id: str, direction_id: int) -> list[str]:
    """The most common ordered list of DHIDs across all trips for (line, dir).

    Trips on a line/direction sometimes vary at the tails (express variants, school
    runs that skip a section). Mode of the full tuple captures the regular trip.
    """
    sub = stop_times.filter(
        (pl.col("line_id") == line_id) & (pl.col("direction_id") == direction_id)
    ).select("trip_id", "stop_seq", "stop_id")
    if sub.is_empty():
        return []
    by_trip = (
        sub.sort("trip_id", "stop_seq")
        .group_by("trip_id", maintain_order=True)
        .agg(pl.col("stop_id"))
    )
    seqs = Counter(tuple(s) for s in by_trip["stop_id"].to_list())
    most_common, _ = seqs.most_common(1)[0]
    return list(most_common)


# ---------------------------------------------------------------- OSM matching

def _osm_relation_stop_members(rel: dict) -> list[tuple[float, float]]:
    """Ordered (lat, lon) of stop/platform node members of an OSM relation."""
    out = []
    for m in rel.get("members", []):
        if m.get("type") == "node" and m.get("role") in ("stop", "platform"):
            lat, lon = m.get("lat"), m.get("lon")
            if lat is not None and lon is not None:
                out.append((lat, lon))
    return out


def load_osm_stop_members_index(raw_path: Path) -> dict[int, list[tuple[float, float]]]:
    """Map osm_rel_id -> ordered list of stop/platform node coords.

    Reads the cached Overpass JSON (90 MB; produced by fetch_routes_osm.py).
    routes_osm.parquet doesn't carry these — it only stores the polyline.
    """
    if not raw_path.exists():
        raise SystemExit(
            f"missing {raw_path} — run "
            "`uv run python pipeline/fetch_routes_osm.py --refresh-raw` first."
        )
    raw = json.loads(raw_path.read_bytes())
    return {
        r["id"]: _osm_relation_stop_members(r)
        for r in raw.get("elements", [])
        if r.get("type") == "relation"
    }


def match_osm_variant(line_id: str, direction_id: int,
                      canon_dhids: list[str],
                      stop_coords: dict[str, tuple[float, float]],
                      osm_candidates: pl.DataFrame,
                      osm_stop_members: dict[int, list[tuple[float, float]]],
                      ) -> dict | None:
    """For one (line, dir), pick the OSM relation that GTFS fully validates.

    Strategy (stop-member match, not polyline-distance):
      1. For each OSM candidate with ref == line_id, look up its ordered
         stop-node members.
      2. Direction filter: GTFS canonical first stop must be closer to the
         OSM relation's first stop-member than to its last — i.e. OSM
         relation drives the same way GTFS does.
      3. Full-coverage check: every GTFS canonical stop must have an OSM
         stop-member within OSM_STOP_TO_STOP_RADIUS_M. Any miss → drop.
      4. Among fully-covering candidates, pick the one with the lowest
         worst-case GTFS↔OSM stop distance (tightest match).
      5. Compute arc-length offsets by projecting GTFS stops onto the
         chosen polyline (geometry stays the same — only the validation
         changed).
    """
    if not canon_dhids or osm_candidates.is_empty():
        return None
    coords = [(d, stop_coords[d]) for d in canon_dhids
              if d in stop_coords and stop_coords[d] is not None]
    if len(coords) < 2:
        return None
    gtfs_first = coords[0][1]
    gtfs_last = coords[-1][1]

    best = None
    for row in osm_candidates.iter_rows(named=True):
        osm_stops = osm_stop_members.get(row["osm_rel_id"], [])
        if len(osm_stops) < 2:
            continue

        # Direction filter — GTFS line and OSM relation must run the same way.
        d_to_osm_start = _haversine_m(gtfs_first, osm_stops[0])
        d_to_osm_end = _haversine_m(gtfs_first, osm_stops[-1])
        if d_to_osm_start > d_to_osm_end:
            continue  # OSM relation is the opposite direction

        # Coverage check: count GTFS stops with an OSM stop-node within radius.
        served = 0
        worst = 0.0
        sum_d = 0.0
        for _, (glat, glon) in coords:
            md = min(_haversine_m((glat, glon), o) for o in osm_stops)
            sum_d += md
            worst = max(worst, md)
            if md <= OSM_STOP_TO_STOP_RADIUS_M:
                served += 1
        coverage = served / len(coords)
        # Reject anything that's not a clear match. Right relations almost
        # always hit >90% with worst miss <500 m; wrong relations miss by km.
        if coverage < MIN_STOP_MATCH_FRAC or worst > OSM_MAX_MISS_RADIUS_M:
            continue

        # Tie-break: prefer higher coverage, then tighter average distance.
        score = (coverage, -sum_d / len(coords))
        if best is None or score > best["score"]:
            poly = _parse_geojson_linestring(row["geometry"])
            offsets = [_project_onto_polyline(g[1][0], g[1][1], poly)[0] for g in coords]
            best = {
                "score": score,
                "coverage": coverage,
                "worst_m": worst,
                "avg_m": sum_d / len(coords),
                "osm_rel_id": row["osm_rel_id"],
                "geometry": row["geometry"],
                "length_m": row["length_m"],
                "colour": row["colour"],
                "offsets": offsets,
            }
    return best


def build_lines(stop_times: pl.DataFrame,
                stops_geo: pl.DataFrame,
                routes_osm: pl.DataFrame,
                trips_meta: pl.DataFrame,
                osm_stop_members: dict[int, list[tuple[float, float]]]) -> pl.DataFrame:
    """One row per (line, direction). Picks canonical OSM variant + offsets."""
    stop_coords = {
        r["dhid"]: (r["stop_lat"], r["stop_lon"])
        for r in stops_geo.iter_rows(named=True)
        if r.get("dhid") and r.get("stop_lat") is not None
    }
    line_dirs = (
        stop_times.select("line_id", "direction_id")
        .unique().sort("line_id", "direction_id")
    )
    headsigns = (
        trips_meta.group_by("line_id", "direction_id")
        .agg(headsign=pl.col("trip_headsign").mode().first(),
             n_trips=pl.len().cast(pl.Int32))
    )

    rows = []
    unmatched = []
    for ld in line_dirs.iter_rows(named=True):
        line_id, dir_id = ld["line_id"], ld["direction_id"]
        canon = canonical_stop_sequence(stop_times, line_id, dir_id)
        coords_in_canon = [stop_coords.get(d) for d in canon]
        coords_kept = [(d, c) for d, c in zip(canon, coords_in_canon) if c is not None]

        # OSM ref tags can be compound (e.g. "5050/5", "36/37/820") when a line
        # carries multiple operator IDs. Split on '/' and match any part to our
        # GTFS line_id. Bare equality first (no false-positives), then expand.
        osm_cands = routes_osm.filter(
            (pl.col("line") == line_id)
            | pl.col("line").str.contains_any([f"/{line_id}", f"{line_id}/"])
        )
        # contains_any is loose ("5" matches "50/5" and "55/X"). Tighten with an
        # exact slash-part membership check.
        if osm_cands.height:
            osm_cands = osm_cands.filter(
                pl.col("line").str.split("/").list.contains(line_id)
            )
        match = match_osm_variant(line_id, dir_id, canon, stop_coords, osm_cands,
                                  osm_stop_members)

        hs = headsigns.filter(
            (pl.col("line_id") == line_id) & (pl.col("direction_id") == dir_id)
        )
        headsign = hs["headsign"].item() if hs.height else None
        n_trips = int(hs["n_trips"].item()) if hs.height else 0

        if match is None:
            unmatched.append((line_id, dir_id))
            rows.append({
                "line_id": line_id, "direction_id": dir_id,
                "headsign": headsign, "colour": DEFAULT_COLOUR,
                "osm_rel_id": None, "geometry": None, "length_m": None,
                "n_trips": n_trips,
                "stop_sequence": canon,
                "stop_offsets_m": [0.0] * len(canon),
                "stop_match_frac": 0.0,
            })
            continue

        # Build offsets list aligned to the FULL canonical sequence (incl. stops
        # with unknown coords — those get the offset from the nearest neighbour
        # via linear interpolation in sequence-index space, or 0 if at the edge).
        offsets_kept = match["offsets"]
        kept_dhids = [d for d, _ in coords_kept]
        kept_idx = {d: i for i, d in enumerate(kept_dhids)}
        full_offsets: list[float] = []
        for d in canon:
            if d in kept_idx:
                full_offsets.append(offsets_kept[kept_idx[d]])
            else:
                # Stop without coords — interpolate from neighbours in canon order.
                full_offsets.append(full_offsets[-1] if full_offsets else 0.0)

        colour = match["colour"] or DEFAULT_COLOUR
        if not colour.startswith("#"):
            colour = "#" + colour
        rows.append({
            "line_id": line_id, "direction_id": dir_id,
            "headsign": headsign, "colour": colour,
            "osm_rel_id": match["osm_rel_id"],
            "geometry": match["geometry"],
            "length_m": match["length_m"],
            "n_trips": n_trips,
            "stop_sequence": canon,
            "stop_offsets_m": full_offsets,
            "stop_match_frac": round(match["coverage"], 3),
        })

    if unmatched:
        print(f"[warn] {len(unmatched)} (line, dir) had no OSM match: {unmatched[:10]}"
              + ("..." if len(unmatched) > 10 else ""))

    return (
        pl.DataFrame(rows, schema={
            "line_id": pl.Utf8, "direction_id": pl.Int8,
            "headsign": pl.Utf8, "colour": pl.Utf8,
            "osm_rel_id": pl.Int64, "geometry": pl.Utf8, "length_m": pl.Float64,
            "n_trips": pl.Int32,
            "stop_sequence": pl.List(pl.Utf8),
            "stop_offsets_m": pl.List(pl.Float64),
            "stop_match_frac": pl.Float32,
        })
        .sort("line_id", "direction_id")
    )


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    outputs = [OUT_LINES, OUT_STOP_TIMES, OUT_SERVICE_DAYS]
    if all(p.exists() for p in outputs) and not args.force:
        print(f"[skip] {', '.join(p.name for p in outputs)} exist. --force to rebuild.")
        return 0

    if not ROUTES_OSM.exists():
        raise SystemExit(f"missing {ROUTES_OSM} — run fetch_routes_osm.py first.")
    if not STOPS_GEO.exists():
        raise SystemExit(f"missing {STOPS_GEO} — run fetch_gtfs.py first.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    g = load_gtfs()
    routes_osm = pl.read_parquet(ROUTES_OSM)
    stops_geo = pl.read_parquet(STOPS_GEO)
    osm_stop_members = load_osm_stop_members_index(OSM_RAW_JSON)
    n_with_stops = sum(1 for v in osm_stop_members.values() if v)
    print(f"[deps] routes_osm={routes_osm.height} stops_geo={stops_geo.height} "
          f"osm_relations_with_stop_members={n_with_stops}/{len(osm_stop_members)}")

    # 1. service_days (cheap)
    sd = build_service_days(g["cal_dates"])
    sd.write_parquet(OUT_SERVICE_DAYS, compression="zstd")
    print(f"[ok] {OUT_SERVICE_DAYS} ({sd.height} rows, "
          f"{OUT_SERVICE_DAYS.stat().st_size/1024:.0f} KB)  "
          f"dates {sd['date'].min()} → {sd['date'].max()}, "
          f"{sd['service_id'].n_unique()} services")

    # 2. stop_times (big, but linear)
    st = build_stop_times(g)
    st.write_parquet(OUT_STOP_TIMES, compression="zstd")
    print(f"[ok] {OUT_STOP_TIMES} ({st.height:,} rows, "
          f"{OUT_STOP_TIMES.stat().st_size/1024/1024:.1f} MB)")

    # 3. lines — needs stop_times to compute canonical sequences.
    trips_meta = g["trips"].select(
        line_id=pl.col("route_id"),
        direction_id=pl.col("direction_id").cast(pl.Int8),
        trip_headsign=pl.col("trip_headsign"),
    )
    lines_all = build_lines(st, stops_geo, routes_osm, trips_meta, osm_stop_members)
    # Strict gate: drop rows that fail the GTFS-stop-coverage threshold. We'd
    # rather ship 76 verified routes than 85 routes where 9 are suspect.
    dropped = lines_all.filter(
        pl.col("stop_match_frac").is_null()
        | (pl.col("stop_match_frac") < MIN_STOP_MATCH_FRAC)
    )
    lines = lines_all.filter(pl.col("stop_match_frac") >= MIN_STOP_MATCH_FRAC)
    lines.write_parquet(OUT_LINES, compression="zstd")
    print(f"[ok] {OUT_LINES} ({lines.height}/{lines_all.height} (line, dir) rows "
          f"kept; threshold stop_match_frac >= {MIN_STOP_MATCH_FRAC:.0%}, "
          f"{OUT_LINES.stat().st_size/1024:.0f} KB)")

    avg_cov = lines["stop_match_frac"].mean() or 0.0
    print(f"[summary] kept {lines.height} routes, avg coverage {avg_cov:.1%}")
    if dropped.height:
        print(f"[dropped] {dropped.height} (line, dir) rows below threshold — "
              f"schedule in stop_times.parquet is unaffected:")
        for r in dropped.iter_rows(named=True):
            cov = r["stop_match_frac"] or 0.0
            reason = "no OSM match" if r["osm_rel_id"] is None else f"cov={cov:.0%}"
            print(f"          line {r['line_id']:<4} dir {r['direction_id']}  "
                  f"{reason:<16}  -> {r['headsign']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
