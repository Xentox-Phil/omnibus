# GTFS — RVV stop coordinates

How `data/parquet/stops_geo.parquet` (every RVV stop's lat/lon) is built, what's
covered, and what's still missing.

## Approach — RVV-native ID join (not name-matching)

We geocode through RVV's **own** master data using `stop_code` as the key:

```
stop_event.stop_code  →  Haltestellen master CSV (Kürzel → DHID)
                      →  RVV GTFS stops.txt (DHID → lat/lon)
```

`stop_code` is RVV's clean operator key (`HBF`, `AKORN`, `BPLZ`, …), so the join
is **deterministic** — no name normalisation, no fuzzy false-positives, no
245 MB download. The DHID (`Globale Haltestellen-Kennung`, e.g. `de:09362:11041`)
is the standard German stop ID and equals the first three colon-fields of a GTFS
`stop_id` (`de:09362:11041:0:1`), so the two join by ID directly.

### Inputs (all committed, tiny)

| File | Role |
| --- | --- |
| `data/raw/Haltestellen und -punkte - Haltestelle.csv` | RVV stop master — `Kürzel` (= `stop_code`) → DHID. Semicolon-delimited, **latin-1**. |
| `data/raw/gtfs_july2025/stops.txt` | RVV **city** feed — DHID → lat/lon (286 `de:09362` stops). |
| `data/raw/gtfs_aug2025/stops.txt` | RVV **region** feed — backfills coords July lacks. |

`assemble.py` joins `stops_geo.parquet` onto every stop-event on `stop_code`
(primary), then coalesces a `stop_name` fallback for the ~127k rows whose
`stop_code` is null (Apr-2025 Line-1 ingest defect, see [`DATA_DEFECTS.md`](./DATA_DEFECTS.md)).
It adds `stop_lat`, `stop_lon`, and `stop_kind`.

## Pipeline

```
uv run python pipeline/fetch_gtfs.py            # build stops_geo.parquet (<1s)
uv run python pipeline/fetch_gtfs.py --force    # rebuild
uv run python pipeline/fetch_gtfs.py --compare  # old gtfs.de vs new coverage
```

`stops_geo.parquet`: one row per `stop_code` — `stop_name`, `dhid`, `stop_lat`,
`stop_lon`, `kind`. Gitignored (regenerable in <1s from the committed inputs).

## Coverage

- **310 / 310 real passenger stops located (100%)** — 308 via DHID→GTFS, 2 via
  hand-filled OSM coords (`Königsstraße`, `Wittelsbacherstraße`, which carry a
  DHID but no coordinate in either feed; `MANUAL_COORDS` in `fetch_gtfs.py`).
- **99.80%** of *all* raw stop-events (3,817,483 / 3,825,227) carry a coordinate;
  the remaining 7,744 are exactly the depot / operational / test rows below.
  `assemble.py` **drops** those, so `features.parquet` is **100%** geocoded — there
  is no real passenger stop-event without a coordinate.
- This assumes the Apr-2025 Line-1 stop-identity back-fill ran (it's part of
  `ingest.py`, so it always has). Before that fix 126,984 rows had `stop_name =
  null` and coverage capped at 96.48% — see [`DATA_DEFECTS.md`](./DATA_DEFECTS.md) §4.
- **14 non-stop codes** carry no coordinate **by design** — depot / subcontractor /
  test / operational markers, tagged via `kind` and documented in
  [`CONTACT_NOTES.md`](./CONTACT_NOTES.md). Filter with `stop_kind != 'stop'`.

### vs the old gtfs.de approach

`--compare` runs the previous method (exact + fuzzy name-match against a
bbox-filtered slice of the 245 MB gtfs.de Germany feed) head-to-head:

| | stops | events |
| --- | --- | --- |
| OLD (gtfs.de name-match) | 301 / 324 | 98.75% |
| NEW (`stop_code` → DHID → GTFS) | **310 / 324** | **99.79%** |

NEW is a **strict superset** — `only-OLD = 0`, so it loses nothing and gains 9
codes (+~38k events), including `Ostpreußenstraße` (30k events) which the old
doc had written off as "genuinely absent from the free feed". RVV's own feed has
it. The legacy `gtfs/regensburg_stops.parquet` snapshot stays committed only so
`--compare` keeps working.

## `kind` values

| `kind` | meaning |
| --- | --- |
| `stop` | passenger stop with coordinates |
| `depot_rvv` | RVV's own depot (`BTH SMO` = `vor LSt`) |
| `depot_sub` | subcontractor depot (`RBO`, `SÖLL`, `Wittl`, `EBEN`, `LAS`, `WAZ`) |
| `operational` | operational marker (`HUK`, `LADE` = "Kein Zustieg") |
| `test` | test stop (`TEST 1`–`4`) |

Glossary + provenance: [`CONTACT_NOTES.md`](./CONTACT_NOTES.md).

## Not from GTFS: route descriptions

The July city feed leaves `route_long_name` **empty**; the Aug feed fills it but
keys to regional line IDs that match only 2/47 of our `line` values. So GTFS
can't translate city lines (`1`, `A`, `C1`, `N2`, `X1`, …) to route paths. That
mapping lives in `Linien_Erklärung.pdf` (line → Kürzel → topology factor) — a
separate PDF extraction, see [`RAW_INPUTS.md`](./RAW_INPUTS.md).

## Year drift

Feeds are the **2025** RVV exports against **2023–2025** stop-event data. Stop
coordinates are time-invariant (RVV doesn't move stops). Route shapes / line
numbers *can* drift; verify before any shape-dependent analysis.
