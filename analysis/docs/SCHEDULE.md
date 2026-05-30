# Schedule + per-line route geometry

How `data/parquet/lines.parquet`, `stop_times.parquet`, and `service_days.parquet`
are built, what they contain, and how trustworthy each piece is.

Built by **`pipeline/fetch_schedule.py`** (depends on `fetch_routes_osm.py` and
`fetch_gtfs.py`). The three parquets together are what the backend loads to
render bus routes on a map AND query schedules / reroutes.

## TL;DR

| Parquet | Rows | Size | Source of truth | Confidence |
| --- | --- | --- | --- | --- |
| `service_days.parquet` | 16,370 | 12 KB | GTFS `calendar_dates.txt` | 100% — direct |
| `stop_times.parquet` | 361,698 | 0.8 MB | GTFS `trips.txt` + `stop_times.txt` + `stops.txt` | 100% — direct |
| `lines.parquet` | **58** of 85 GTFS (line, dir) pairs | 90 KB | GTFS canonical sequence + OSM relation polyline, **double-validated** | every kept row passes 4 independent checks; avg stop match 98.6%, min 91.7% |

Schedule data is authoritative (it's RVV's own GTFS). Route geometry is mined
from OpenStreetMap and **gated on GTFS agreement** — if OSM and GTFS disagree
on which stops a line serves, we drop the row rather than ship a polyline that
doesn't follow the real route.

## Why we needed this in the first place

RVV's GTFS feeds (`gtfs_july2025`, `gtfs_aug2025`) ship a **74-byte
header-only `shapes.txt` stub** and have `trips.shape_id = null` on every row.
So GTFS gives us the schedule but no road geometry. We chase the geometry
through OSM `route=bus` relations (community-mapped polylines for each RVV
line) and validate every match against GTFS before keeping it.

Full backstory of the GTFS feeds: [`docs/GTFS.md`](./GTFS.md).

## The four validation checks

Every (line, direction) kept in `lines.parquet` passes all four:

1. **OSM `ref` tag matches GTFS `line_id`** — exact (`"1" == "1"`) or as a
   slash-part of a compound ref (`"5050/5"` carries `"5"` for the city line
   that doubles as regional `5050`).
2. **Direction alignment** — GTFS canonical first stop is closer to the OSM
   relation's first stop-member than to its last. OSM relations are
   directional in the modern `public_transport:version=2` scheme, so each
   GTFS direction matches its own OSM relation.
3. **Stop-member coverage** — every GTFS canonical stop must have a
   corresponding OSM stop-node in the same relation within 100 m. We compare
   **stop-to-stop, not stop-to-road**: OSM tags `role='stop'` at the road
   position while RVV uses platform centroids, so platform-to-road offsets of
   70-90 m at terminals are normal. Threshold tolerates that but is far below
   the ~200-300 m gap between neighbouring RVV stops, so we can't cross-match
   different stops. **MIN_STOP_MATCH_FRAC = 0.90** = 90% of GTFS stops must
   hit; the remaining 1-2 outliers per line are OSM mapping artifacts (same
   stop placed at slightly different coords by different contributors),
   confirmed by their offsets being in the 100-350 m range vs km for actual
   wrong-relation candidates.
4. **Worst-case sanity** — the most-distant single stop must still be under
   500 m. Right-relation outliers cluster at 100-350 m; wrong-relation misses
   are 3-7 km. The 500 m cliff catches anything that wouldn't pass eyeballing
   on a map.

When multiple OSM candidates pass all four, the matcher picks the one with
the highest coverage, breaking ties by lowest average stop distance.

## Quality numbers (current build)

```
58 of 85 GTFS (line, dir) pairs kept
avg stop_match_frac = 0.986
min stop_match_frac = 0.917
```

**Core city lines all retained, both directions:**
`1, 2, 3, 4, 4A, 6, 7, 8, 8A, 9, 10, 11, 18, 39, C1, C2, C4, C6, X1, X4, X9`

**27 dropped** — schedule for these still lives in `stop_times.parquet`,
they just don't render a polyline:

- Regional lines `5`, `70`, `78` — compound OSM refs didn't resolve cleanly to
  the city-line `route_id` we use.
- New / specialty lines: `B` (Mobilitätsdrehscheibe shuttle — not yet mapped
  in OSM), `D`, `Dult/1`.
- Most night lines: `N1/1`, `N2/1`, `N4/1`, `N6/1`, `N7` (both). `N3/1` and
  `N5/1` kept.
- School / express variants with low trip counts: `11A/0`, `32/0`, `72/1`,
  `73/1`, `75/0`, `80` (both), `A/0`.

The drops are honest gaps in OSM coverage, not pipeline bugs. Recovering them
requires either:
- Asking RVV directly for their internal shape data (definitive fix, blocks
  on a sponsor email).
- Hand-editing OSM to add the missing relations (slow).
- Relaxing the gate (would ship suspect geometry).

## Output schemas

### `lines.parquet` — one row per (line, direction)

| Column | Type | Notes |
| --- | --- | --- |
| `line_id` | `str` | `"1"`, `"C2"`, `"N3"` — matches GTFS `route_short_name` and OSM `ref` |
| `direction_id` | `i8` | `0` / `1` — GTFS direction |
| `headsign` | `str` | most common `trip_headsign` for this (line, dir) |
| `colour` | `str` | `"#75B95B"` — from OSM `colour` tag, falls back to default RVV green |
| `osm_rel_id` | `i64` | which OSM variant we picked (for traceability) |
| `geometry` | `str` | **GeoJSON LineString** of the chosen OSM polyline |
| `length_m` | `f64` | polyline length |
| `n_trips` | `i32` | count of trips on this (line, dir) in GTFS |
| `stop_sequence` | `list[str]` | ordered DHIDs — the canonical (modal) stop sequence |
| `stop_offsets_m` | `list[f64]` | meters along the polyline per stop, **parallel to stop_sequence** |
| `stop_match_frac` | `f32` | fraction of canonical stops within 100 m of an OSM stop-member (≥0.90 for every kept row) |

`stop_offsets_m[i]` is the arc-length distance from the start of the polyline
to the projection of stop `stop_sequence[i]`. Use it to find "which stops are
between km 4 and km 6 of this line" in O(N) — no geometric queries needed at
runtime.

### `stop_times.parquet` — one row per (trip, stop)

| Column | Type | Notes |
| --- | --- | --- |
| `trip_id` | `str` | opaque GTFS trip id |
| `line_id` | `str` | denormalised from `trips.route_id` |
| `direction_id` | `i8` | denormalised |
| `service_id` | `str` | join key into `service_days.parquet` |
| `stop_seq` | `i16` | GTFS stop_sequence (1-based, order along the trip) |
| `stop_id` | `str` | DHID, normalised (no `:platform:N` suffix) |
| `stop_name` | `str` | denormalised — saves a join at query time |
| `lat`, `lon` | `f64` | denormalised stop coords |
| `arr_s`, `dep_s` | `i32` | **seconds since service-day midnight** — handles 25:30 cleanly |

Times are integer seconds (not strings) so range queries are math:
"trips arriving at this stop between 17:00 and 18:00" is
`arr_s.is_between(17*3600, 18*3600)`.

### `service_days.parquet` — one row per (date, service_id)

| Column | Type | Notes |
| --- | --- | --- |
| `date` | `date` | parsed from GTFS `YYYYMMDD` |
| `service_id` | `str` | join key into `stop_times` |

The July feed encodes all service activations via `calendar_dates.txt`
(`calendar.txt` is empty), so this is a direct projection. Validity window:
**2025-07-25 → 2025-12-31**, 1005 distinct service_ids.

## How the backend uses it

```python
import polars as pl

# Startup — load everything once.
lines        = pl.read_parquet("data/parquet/lines.parquet")          # ~58 rows
stop_times   = pl.read_parquet("data/parquet/stop_times.parquet")     # ~361k rows
service_days = pl.read_parquet("data/parquet/service_days.parquet")   # ~16k rows
stops_geo    = pl.read_parquet("data/parquet/stops_geo.parquet")      # ~324 stops

# What lines run on a given date?
import datetime as dt
date = dt.date(2025, 9, 15)
active_services = service_days.filter(pl.col("date") == date)["service_id"].to_list()
todays_trips = stop_times.filter(pl.col("service_id").is_in(active_services))

# What time does line 1 hit Hauptbahnhof at ~17:30?
hbf = "de:09362:11041"  # DHID lookup via stops_geo
window = (
    todays_trips
    .filter((pl.col("line_id") == "1") & (pl.col("stop_id") == hbf))
    .filter(pl.col("arr_s").is_between(17*3600, 18*3600))
    .sort("arr_s")
)
```

For reroute logic:
```python
# Affected stops on line 1 dir 0, given a closure between km 4 and km 6
line1 = lines.filter((pl.col("line_id") == "1") & (pl.col("direction_id") == 0)).row(0, named=True)
seq, offs = line1["stop_sequence"], line1["stop_offsets_m"]
affected_dhids = [s for s, o in zip(seq, offs) if 4000 <= o <= 6000]
```

The `geometry` column is GeoJSON, ready for Leaflet / Maplibre / Mapbox /
Folium without conversion.

## Tuning the strictness gate

Constants at the top of `pipeline/fetch_schedule.py`:

```python
OSM_STOP_TO_STOP_RADIUS_M = 100.0   # "same logical stop in both datasets"
MIN_STOP_MATCH_FRAC       = 0.90    # ≥90% of GTFS stops must match
OSM_MAX_MISS_RADIUS_M     = 500.0   # worst single-stop offset allowed
```

- **Tighter** (`100% / 100 m`): ~43 routes kept. Drops anything with even a
  single OSM mapping outlier. Lossy.
- **Current** (`90% / 100 m / 500 m`): 58 routes. Best balance — every kept
  row visually verifiable on a map.
- **Looser** (`80% / 150 m / 750 m`): ~70 routes, but starts including
  variant relations that skip a section.

Each kept row's `stop_match_frac` lets the backend filter further at query
time without re-running the pipeline.

## Run it

```bash
uv run python pipeline/fetch_routes_osm.py     # downloads ~90 MB Overpass JSON, caches to data/raw/osm/
uv run python pipeline/fetch_schedule.py       # joins GTFS + OSM, validates, writes 3 parquets

uv run python pipeline/fetch_schedule.py --force   # rebuild after tuning the constants
```

Both are idempotent — skip if outputs exist. The OSM fetch caches the raw
Overpass response at `data/raw/osm/bus_routes.json` (~90 MB, gitignored); the
schedule build reads that cache for OSM stop-member positions without
re-hitting the network.

## What this pipeline is NOT

- Not the modelling table — that's [`features.parquet`](../README.md#the-features-table-featuresparquet),
  one row per stop-event with weather/holiday/event context joined on. The
  schedule parquets here are for the *live* product (map + reroute backend),
  not for delay analysis.
- Not authoritative on the geometry side. OSM is community-mapped; we trust
  it only where GTFS confirms it. The definitive geometry would come from
  RVV's own shape data (their dispatch system has it; they just didn't share
  it in the GTFS export they gave us).
