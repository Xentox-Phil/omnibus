# Omnibus

Hackaburg 2026 project. Public transit optimization for **RVV** (Regensburg).

## What we're building

Two products on the same dataset:

1. **Daytime fleet optimizer** — weather + event-aware bus type & count allocation per line per hour. Predicts delays.
2. **Night on-demand ride** — after ~20:00, scheduled service replaced by bookable pooled rides. Mobile app + station kiosk for booking.

Full plan, role split (5 people), ML model specs, demo script → see [`PLAN.md`](./PLAN.md).

## Repo layout (target)

```
data/                  # parquet, stops, weather (gitignored if big)
services/
  ml/                  # delay + demand models, /eta endpoint
  optimizer/           # PuLP fleet allocator, /allocation endpoint
  dispatch/            # night booking, matching, vehicle sim, WS
apps/
  operator/            # Next.js — fleet-allocation dashboard
  kiosk/               # Next.js — station touch UI
  mobile/              # Expo — rider app
Hackaburg_2026/        # raw CSV dataset from RVV (DO NOT commit, large)
docs/
PLAN.md                # full plan + role split + ML spec
CLAUDE.md              # this file
```

## Dataset quirks (read before touching CSVs)

- **Encoding: UTF-16**. `pandas.read_csv(path, encoding='utf-16')` or `polars.read_csv(path, encoding='utf-16')`. Plain `open()` gives garbage.
- **Delimiter:** comma, but with quoted fields — standard CSV.
- **Columns are German.** See bottom of this file for the canonical translation.
- **Some columns are empty** in the header (positions 10, 12, 14, 17, 19 carry sub-values like "Hauptbahnhof" — second name for same stop, etc.). Don't drop them blindly; inspect.
- **Date format:** `DD.MM.YYYY HH:MM:SS` (German). Parse with `format="%d.%m.%Y %H:%M:%S"`.
- **No passenger counts.** APC data exists at RVV but was not shared. We infer demand from dwell time (see `PLAN.md` Person 2 → Model B).
- **No weather columns.** Join externally via Open-Meteo or DWD station Regensburg (03379).
- **Files in `Hackaburg_2026/`:**
  - `06.10.2024_19.10.2024_ITCS.csv` — baseline 2-week sample (univ + OTH mixed)
  - `08.10.2023_21.10.2023_ITCS.csv` — same period 2023 (baseline year-over-year)
  - `15.12.2024_25.12.2024_ITCS_Christkindlmarkt2024.csv` — Christmas market event
  - `23.04.2025_09.05.2025_ITCS_nur_UniLinien.csv` — university lines only (2, 4, 6, 11, C1/C2/C4/C6, X4)
  - `26.05.2024_07.06.2024_ITCS_Hochwasser.csv` — June 2024 flood (peak 02.06.24, Meldestufe 4, 5.5m)
  - `Daten Linie 1_2026-05-20_152040.zip` — full year 2025 for Line 1 only

## Conventions

- **Language:** code English, comments English. UI strings German (Regensburg users).
- **stop_id** is the canonical stop reference everywhere. Defined in `data/stops.csv` (Person 1 ships hour 1).
- **Timestamps:** ISO 8601 UTC in APIs, German local in raw data — convert at the parquet boundary.
- **Money/CO2 numbers** in the optimizer are made-up plausibles, not audited. Don't claim otherwise externally.
- **Backend services** are all FastAPI on different ports during dev; one shared `docker-compose.yml` for the demo.
- **Frontends** call backend via TanStack Query.

## Running things

Specifics TBD per service (will be added to each service's README as it's built). General pattern:

```bash
# ML / optimizer / dispatch services (Python)
cd services/<name> && uv sync && uv run uvicorn main:app --reload --port <port>

# Frontend apps
cd apps/<name> && pnpm install && pnpm dev
```

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

- **Weather:** Open-Meteo historical & forecast (https://open-meteo.com — no key, free) for Regensburg (`lat=49.013, lng=12.101`). Fallback: DWD station 03379.
- **GTFS / stop coordinates:** RVV GTFS feed (search "RVV Regensburg GTFS" via gtfs.de, transit.land, or RVV open data portal). **Required hour 1** — blocks dispatch + frontend.
- **Routing:** OSRM (public demo `https://router.project-osrm.org` for dev, local Docker with Regensburg .osm.pbf extract for demo reliability).
- **Bavarian school holidays:** for `school_holiday` feature in delay model. Static CSV is fine.

## Don'ts

- Don't commit the raw `Hackaburg_2026/*.csv` files — they're huge, gitignored.
- Don't claim demand is real passenger count — always say "dwell-based demand proxy".
- Don't trust public OSRM under demo load — local Docker for the actual presentation.
- Don't use `event_tag` as an inference-time feature without explicitly setting it (it's known in training, ambiguous in production).
- Don't add APC integration paths — RVV won't share APC; document the proxy approach.
