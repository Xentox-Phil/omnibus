# Raw inputs — what we have and what we can do with it

Catalog of everything in `analysis/data/raw/`. The pristine received bundles live
in `analysis/data/_originals/` (zips + `Reference/`); `raw/` is those unpacked into
the paths the pipeline expects. Layout & rebuild mechanics: [`../data/README.md`](../data/README.md).

**Commit legend:** ✅ committed · ❌ gitignored (not redistributable or large/regenerable).

| Input | What it is | Committed | Deep doc | What we can do with it |
| --- | --- | --- | --- | --- |
| `rvv/*.csv` (5 windows) + `rvv/Daten Linie 1/` | RVV ITCS stop-event exports (UTF-16, German cols). The core dataset. | ❌ not redistributable | [`DATA_DEFECTS.md`](./DATA_DEFECTS.md), [`UNIQUE_IDS.md`](./UNIQUE_IDS.md), col map in [`CLAUDE.md`](../../CLAUDE.md) | Everything: delay, dwell, reliability σ, bunching, flood/event impact. Built into `features.parquet`. |
| `gtfs/regensburg_stops.parquet` | 86 KB bbox extract of the gtfs.de feed. | ✅ | [`GTFS.md`](./GTFS.md) | Stop coordinates → `stops_geo.parquet` → all map views. |
| `gtfs_july2025/`, `gtfs_aug2025/` | Full GTFS feeds (unzipped, ~56 MB). | ❌ re-fetchable, not yet used | [`GTFS.md`](./GTFS.md) | Routes, shapes, scheduled headways, trip geometry — **untapped**: route polylines for the map, planned vs actual headway. |
| `oth_ics/*.ics` | OTH semester calendars. | ✅ fragile upstream | [`EXTERNAL_DATA.md`](./EXTERNAL_DATA.md) | `university_calendar.parquet` (lecture-period flags). |
| `events_regensburg_2024_2025.csv` | Hand-researched events, per-row source URLs. | ✅ | [`EVENTS.md`](./EVENTS.md), [`EVENTS_FORMAT.md`](./EVENTS_FORMAT.md) | `events_regensburg.parquet` — demand spikes (Dult, Jahn, markets). |
| `strikes_rvv_2024_2025.csv` | Hand-researched strikes. | ✅ | [`STRIKES.md`](./STRIKES.md) | `strikes_rvv.parquet` (null-finding: no ÖPNV strikes hit RVV). |
| `betriebskalender_events.csv` | 98 rows hand-pulled from the 3 SMO PDFs. | ✅ | [`BETRIEBSKALENDER.md`](./BETRIEBSKALENDER.md) | Operational annotations not in any other source: FP-Wechsel, X1 school reinforcement, Heiligabend/Silvester Saturday-timetable, Eislauf Linie D. |
| `*_SMO_Betriebskalender.pdf` (2023/24/25) | Source PDFs for the row above. | ✅ small text PDFs | [`BETRIEBSKALENDER.md`](./BETRIEBSKALENDER.md) | Re-extract / verify the CSV; legend reference. |
| `Linien_Erklärung.pdf` | INIT/ITCS **line master**. | ✅ | _this file, below_ | Line-number → public-code map; per-line topology factor. |
| `Haltestellen und -punkte - Haltestelle.csv` | RVV **stop master** w/ coords + global IDs. | ✅ | _this file, below_ | Independent geocoding source / GTFS cross-check. |
| `Population_Regensburg_2023/` | 473 census zones, residents by age group. | ✅ ⚠️ license | _this file, below_ | Spatial demand proxy — population in each stop catchment. |

---

## Linien_Erklärung.pdf — the line master

INIT Mobility Software export (the ITCS vendor), version `Basisversion_Regensburg`,
validity 2020–2030. One row per line. Columns:

- **Nummer** — internal line number (e.g. `53`, `61`, `204`).
- **Kürzel / Name** — public code (e.g. `X1`, `C1`, `X4`). **This is the join we
  need:** RVV CSVs and GTFS sometimes carry the internal number, the public world
  uses the Kürzel (e.g. `61 → C1`, `204 → X4`, `53 → X1`).
- **Topologiefaktor** — per-line complexity weight, 1.00–1.50 (e.g. line 8 = 1.50,
  line 2 = 1.20). RVV's own notion of how demanding a line's topology is — a
  ready-made feature/baseline for "expected difficulty" when normalising delays.
- **Betriebszweige** — all `1 - Bus`. **Versionen** — count of timetable variants.
- Second table: Externe Liniennummer, Linienlänge, Konzessionär (mostly blank).

**Use:** build a `line → kürzel → topology_factor` lookup; normalise reliability by
topology factor; resolve the C/X line-code mapping once, centrally.

## Haltestellen und -punkte - Haltestelle.csv — the stop master

Semicolon-delimited, **latin-1** encoding, 377 stops. Read with
`pl.read_csv(path, separator=';', encoding='latin-1')`. Key columns:

- **Nummer / Kürzel / Langname / Kurzname** — stop IDs and names.
- **X-Koord / Y-Koord** — lon / lat (≈12.0x / 49.0x; a few boundary stops are 0).
- **Globale Haltestellen-Kennung** — DHID like `de:09362:880` — the standard German
  stop ID, joinable to GTFS `stops.txt` and to any DELFI/national dataset.
- Anz. Pos. (number of stop points), Ansage-Nr., Funkgestützt, etc.

**Use:** a second coordinate source to fill the ~4.5% of stops GTFS misses (see
[`GTFS.md`](./GTFS.md)); the DHID gives a clean key to join GTFS ↔ ITCS ↔ national
feeds by ID instead of fuzzy stop-name matching.

## Population_Regensburg_2023/ — census zones

ESRI shapefile (`.SHP/.SHX/.DBF/.PRJ` + `.qix` index), 473 zone polygons.
Read with `geopandas.read_file(".../*.SHP")`. DBF attributes:

- **NO / CODE / NAME** — zone id + label.
- **SG_1_EW_1 … SG_1_EW_12** — residents (Einwohner) per age group; bins defined in
  `Erklarung_zum_Alter.docx`.
- **youth16-24** — the student-age cohort (directly relevant: uni-line demand).
- **Shuttle** — a flag (purpose TBD — likely shuttle-served zone).

**Use:** spatial-join stops to zones → population (esp. youth16-24) within each stop's
catchment → a *static* demand prior to pair with the *dynamic* dwell-time proxy
(Model B). Answers "is this stop under-/over-served relative to who lives around it?"

> **License:** city/Heidelberg analysis model, source license unverified. Fine to keep
> in-repo for the hackathon; recheck before any public release.

## Not-yet-tapped

- **GTFS `shapes.txt` / `routes.txt`** — route polylines for proper on-map route
  rendering (currently stops only).
- **GTFS `stop_times.txt`** — scheduled headways → planned-vs-actual headway, a cleaner
  bunching baseline than inferring schedule from the ITCS data.
- **Population × dwell** — the static-prior + dynamic-proxy demand model above.
