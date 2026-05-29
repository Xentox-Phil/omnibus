# GTFS — RVV stop coordinates

How `data/parquet/stops_*.parquet` (the inputs that give every RVV stop a
lat/lon) are built, what's covered, and what's still missing.

## Source

[**gtfs.de Germany free aggregator**](https://gtfs.de/de/feeds/) — single zip,
nationwide, refreshed weekly. The "free" tier has agencies + stops + routes +
trips + stop_times for all public-transit operators in Germany (~687k stops).
**No `shapes.txt`** in the free tier — that needs the paid feed or RVV's own
GTFS export. Doesn't block Scene B; does block Scene A's per-segment
map-matching (we'd be limited to straight-line stop-to-stop hops).

URL: `https://download.gtfs.de/germany/free/latest.zip` (~245 MB).

## Pipeline (two-tier — mirrors events/strikes CSV pattern)

| File | Where | Tracked? | Built by |
| --- | --- | --- | --- |
| `regensburg_stops.parquet` (~4,010 rows, ~86 KB) | `data/raw/gtfs/` | **committed** | `fetch_gtfs.py --refresh-raw` (downloads 245 MB zip, bbox-filters, writes the snapshot, deletes the zip) |
| `stops_geo.parquet` (~304 rows, ~9 KB) | `data/parquet/` | gitignored, regenerable | `fetch_gtfs.py` (default — reads the committed raw snapshot + RVV window parquets, runs the name-match) |

**Default invocation** (`fetch_gtfs.py` with no flags): reads the committed raw
snapshot, runs the join, writes `stops_geo.parquet`. Takes <1 second. This is
what teammates run after `git clone` — **no 245 MB download**.

**Refreshing the raw snapshot** (rarely needed — RVV doesn't move stops):
`fetch_gtfs.py --refresh-raw` re-downloads the zip, extracts, bbox-filters,
overwrites `regensburg_stops.parquet`, deletes the zip + `stops.txt`.

`assemble.py` left-joins `stops_geo.parquet` by `stop_name`, adding `stop_lat`
and `stop_lon` columns to every stop-event in `features.parquet`.

## Matching strategy

1. **Exact name match** against the bbox extract (covers 92.9% of stops, ~94% of events).
2. **Fuzzy fallback** — normalise (lowercase + umlaut/ß folding), then substring
   match either direction; tie-break by shortest GTFS name to bias toward
   exact-ish hits. Adds 3 stops. Operator/depot codes (all-caps ≤4 chars,
   `BTH/DTH/MTH` suffixes, `Testhaltestelle`, `Kein Zustieg`, `vor LSt`) are
   excluded from fuzzy match to prevent false positives.

## Coverage

- **304 of 324** unique RVV stop names matched (93.8%).
- **98.84%** of named stop-events (3,655,177 / 3,698,243) have coordinates.
- **95.55%** of *all* stop-events (3,655,177 / 3,825,227). The 127,000-event
  gap between the two numbers is rows with `stop_name = null` — the Apr 2025
  Line-1 ingest defect (§4), unrelated to GTFS.

## Outliers — what's still missing

| Stop name | Events | Why missing | Recoverable? |
| --- | ---: | --- | --- |
| `(null)` | 126,984 | Ingest defect §4 — Apr 2025 Line-1 month lacks `Haltestelle` column. Stop identity is null *upstream*, not a matching failure. | Yes, via `stop_point ↔ stop_code` join from months that have both. Flagged for analysis layer. |
| `Ostpreußenstraße` | 30,123 | Real RVV stop, genuinely absent from the gtfs.de **free** feed. Likely served by an agency not in the free tier. | Yes — paid gtfs.de tier, or RVV's own GTFS, or one-shot OSM Overpass lookup. |
| `SMO BTH` | 2,676 | Depot / operator code (Stadtbus-Mobile or similar), not a passenger stop. | No — operational metadata, won't have a coordinate. |
| `Königsstraße` | 2,390 | Real stop missing from feed (probably a spelling/agency issue). | Yes — manual lookup or OSM. |
| `HUK` | 2,217 | Operator/route code. | No. |
| `Kein Zustieg` | 1,157 | German for "no boarding" — operational flag, not a stop. | No. |
| `Irl West` | 900 | Real Landkreis stop, missing from free feed. | Yes — OSM. |
| `Werner-Heisenberg-Straße` | 900 | Real stop, missing. | Yes — OSM. |
| `vor LSt` | 509 | Operational ("before signal"), not a stop. | No. |
| `Watzinger`, `Wittelsbacherstraße`, `Tegernheim M-Luther-Kirche`, `Tegernheim Gh Federl` | ~330 each | Real stops, missing from free feed. | Yes — OSM. |
| `RBO`, `Wittl`, `Laschinger`, `Ebenbeck` | <200 each | Looks like operator/depot codes (RBO = Regionalverkehr Bayern Ost?). | Probably not. |
| `Testhaltestelle 1-4` | <40 each | Test stops, not real. | No. |

**Net real-stop misses:** ~7 stops covering ~35k events (~0.9%). All are
recoverable via OSM Overpass or a richer GTFS source — not chased for the
hackathon timeline.

## How to improve coverage (when time permits)

1. **OSM Overpass query** for `highway=bus_stop` in the bbox, name-match the
   ~7 real missing stops. ~30 min of work, ~1% extra coverage.
2. **Paid gtfs.de feed** — closes the free-tier gap entirely. €/month.
3. **RVV's own GTFS** — if they publish one. The data we already have suggests
   they probably do internally. Worth an email.
4. **Back-fill `Daten_Linie_1` April 2025 nulls** via `stop_point → stop_code`
   from adjacent months that have the column (defect §4). Recovers ~127k events
   at one stroke — by far the highest-leverage fix.

## Year drift

We're using the **current** (~2026) feed against **2023–2025** stop_event data.
Stop coordinates are essentially time-invariant — RVV doesn't move bus stops.
What *could* drift: route shapes (if a line was rerouted) and line numbers (RVV
did a `C` rebrand a while back). Verify with a spot-check before any
shape-dependent analysis (Scene A).
