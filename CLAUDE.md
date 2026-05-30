# Omnibus

Hackaburg 2026 project. Public transit optimization for **RVV** (Regensburg).

See [`BRIEF.md`](./BRIEF.md) for the challenge prompt, sponsor wishes, and judging criteria (Technical Difficulty, Innovation, Impact, UI/UX, Presentation).

> **Scope note:** The `drone/` directory is an **unrelated side project**. Do **not** propose drone/hardware tie-ins for Omnibus.

## Repo layout

- `analysis/` — Python data pipeline (uv-managed, `pyproject.toml` + `uv.lock`). All data lives here: `analysis/pipeline/`, `analysis/data/` (raw + parquet — **gitignored**, regenerable), `analysis/docs/`. Run scripts from inside `analysis/` via `uv run python pipeline/<script>.py`. See [`analysis/README.md`](./analysis/README.md).
- `backend/` — FastAPI app (uv-managed). **Thin dummy stub** serving the demand artifacts (`GET /demand/{date}`, `/events/{date}`). The frontend can also read the static `analysis/data/demand/*.json` directly; flesh out the API only if needed.
- `frontend/` — TanStack Start web app. Map + demand heatmap + per-event curves + flex-route proposals.
- **Active plan: [`PLAN.md`](./PLAN.md)** (root) — demand / on-demand flex-bus.
- `ideas/_archive/` — earlier discarded iterations (incl. the reroute-on-closure B-plan).
- `drone/` — unrelated side project (ignore).

## Dataset quirks (read before touching CSVs)

- **Encoding: UTF-16**. `pandas.read_csv(path, encoding='utf-16')` or `polars.read_csv(path, encoding='utf-16')`. Plain `open()` gives garbage.
- **Delimiter:** comma, but with quoted fields — standard CSV.
- **Columns are German.** See bottom of this file for the canonical translation.
- **Some columns are empty** in the header (positions 10, 12, 14, 17, 19 carry sub-values like "Hauptbahnhof" — second name for same stop, etc.). Don't drop them blindly; inspect.
- **No passenger counts.** APC data exists at RVV but was not shared. We infer demand from **dwell time** — the core of the active plan. `dwell_s` per `(stop × hour × dow)` over a full year → a demand surface (`analysis/pipeline/predict_demand.py`).
- **No weather columns.** Join externally via Open-Meteo or DWD station Regensburg (03379).
- **Dataset inventory + where to drop raw files:** [`analysis/data/README.md`](./analysis/data/README.md) — single source for what each RVV window is, exact filenames, and folder layout.

## German → English column map

| German                              | English (use in parquet)                 |
| ----------------------------------- | ---------------------------------------- |
| Ankunft Haltestelle (Tür)           | ts_arrival_actual_door                   |
| Ankunft Haltestelle (Halt)          | ts_arrival_actual_halt                   |
| Ankunft PLAN (Haltestelle)          | ts_arrival_planned                       |
| Abfahrt Haltestelle (Tür)           | ts_departure_actual_door                 |
| Abfahrt Haltestelle (Halt)          | ts_departure_actual_halt                 |
| Abfahrt PLAN (Haltestelle)          | ts_departure_planned                     |
| Ankunft produktiv                   | productive_arr (bool: "Ja"→true)         |
| Abfahrt produktiv                   | productive_dep (bool)                    |
| Betriebstag                         | operating_day (can be >24h, may overlap) |
| Fahrtbeginn (Soll-Haltestelle)      | trip_start_stop                          |
| Fahrtende (Soll-Haltestelle)        | trip_end_stop                            |
| Haltestelle                         | stop_name                                |
| Haltepunkt                          | stop_point (>=1 per stop)                |
| Linie                               | line                                     |
| Richtung                            | direction                                |
| Umlauf                              | vehicle_block (depot-to-depot duty)      |
| Fahrplan-Abw. Abfahrt (Tür) AVG {s} | delay_dep_avg_s                          |
| Fahrplan-Abw. Ankunft (Tür) AVG {s} | delay_arr_avg_s                          |
| CUMSUM(Distanz PLAN) {m}            | distance_cum_m                           |
| CUMSUM(Fahrzeit IST) {s}            | runtime_cum_s                            |

**Key fields to derive:**

- `delay_arr_s = ts_arrival_actual_door - ts_arrival_planned`
- `dwell_s = ts_departure_actual_door - ts_arrival_actual_door`
- `door_opened = ts_arrival_actual_door is not null` (if only halt timestamp exists, doors never opened)

## External data sources

Fetchers under `analysis/pipeline/fetch_*.py` write to `analysis/data/parquet/`. All are idempotent (skip if output exists; `--force` to refetch). Details — APIs used, naming quirks, manual fallbacks — in [`analysis/docs/EXTERNAL_DATA.md`](./analysis/docs/EXTERNAL_DATA.md).

- **Weather + daylight** (Open-Meteo) → `weather_regensburg.parquet` (hourly) + `daylight_regensburg.parquet` (daily sunrise/sunset/daylight_hours)
- **Bavarian public + school holidays** (Open-Holidays-API) → `holidays_bavaria.parquet`
- **OTH + UR semester calendars** → `university_calendar.parquet` (needs holidays parquet built first)
- **Regensburg events** (manual CSV in `data/raw/`, per-row source URLs) → `events_regensburg.parquet`. Methodology + sources in [`analysis/docs/EVENTS.md`](./analysis/docs/EVENTS.md).
- **RVV-relevant strikes** (manual CSV) → `strikes_rvv.parquet`. **Null finding:** no ver.di bus driver strikes hit RVV in 2024/25 (Bayern in Friedenspflicht). Methodology in [`analysis/docs/STRIKES.md`](./analysis/docs/STRIKES.md).
- **GTFS / stop coordinates:** RVV GTFS feed — **required hour 1**, blocks dispatch + frontend. Search "RVV Regensburg GTFS" via gtfs.de, transit.land, or RVV open data portal.
- **Routing:** OSRM (public demo for dev, local Docker w/ Regensburg `.osm.pbf` for demo reliability).

## Parquet outputs (`analysis/data/parquet/`)

> Gitignored + regenerable — layout, commit status, and rebuild steps in [`analysis/data/README.md`](./analysis/data/README.md).

- `<event-window>.parquet` — one per RVV CSV (see `analysis/pipeline/ingest.py`).
- `Daten_Linie_1_2024-09_2025-08.parquet` — Line 1 full year (melted monthly CSVs, pivoted).
- `weather_regensburg.parquet` — hourly weather, 2023-01-01 → recent.
- `daylight_regensburg.parquet` — daily sunrise / sunset / daylight_hours, same range as weather.
- `holidays_bavaria.parquet` — daily public + school holidays for Bavaria, 2023–2026.
- `university_calendar.parquet` — daily `in_session` flag per institution (`oth`, `ur`), 2023-03 → 2026-07.
- `events_regensburg.parquet` — 345 day-rows of confirmed Regensburg events (Jahn, Eisbären, Dult, Christkindlmarkt, Schlossfestspiele, Marathon, Bürgerfest), 2024–2026, each row sourced.
- `strikes_rvv.parquet` — 3 day-rows of TVöD/TV-V Stadtwerke strikes 2025; bus-driver impact `unknown` (Bayern was in Friedenspflicht throughout, no ÖPNV strikes).
