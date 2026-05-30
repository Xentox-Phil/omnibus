# Omnibus — Plan (reroute v2)

> **Pitch:** *"Draw a closure on the map. We tell the operator which bus lines break, which stops are stranded, and offer three reroute options for each — each option is a different trade-off between preserving the timetable and preserving stops."*

> **Pivot history:** This is the third iteration of the plan.
> 1. Original (committed): three-scene analytical story (Pulse / Reliability / Contagion). Discarded.
> 2. Iteration 2: demand digital-twin. See [`../_archive/demand-twin.md`](../_archive/demand-twin.md). Discarded.
> 3. Iteration 3 (**this doc**): reroute-on-closure with operator-chosen alternatives. The reroute idea existed before (see [`../_archive/reroute-v1.md`](../_archive/reroute-v1.md)) — this version refines the UX and locks the architecture.
>
> The `analysis/` data pipeline is shared across all iterations; nothing in there is wasted.

---

## The problem

RVV constantly closes roads — construction, events (Bürgerfest, Dult, Christkindlmarkt, Jahn home games), floods. Every closure forces a manual reroute decision and silently strands stops. There is no tool that helps the operator pick the *best* reroute.

## What we're building

A web app:

1. Open a map of Regensburg with all RVV bus lines drawn.
2. Either **draw a polygon** marking a closure, or pick a **preset event** (Bürgerfest weekend, June 2024 flood) from the events parquet.
3. The map immediately shows all affected lines re-routed around the polygon, and a **side panel lists each affected line** with its impact summary.
4. Click a line in the side panel → map focuses on that line; you see the **original route, the polygon, and up to 3 reroute alternatives** (Google-Maps-style). Each alternative is a different operator trade-off: preserve-timetable / preserve-stops / shortest-detour. The operator picks one.

## The metric we optimize

A reroute is good if **riders still get picked up close to when the timetable promised**.

```
cost = Σ |t_new(stop) − t_planned(stop)|   ← deviation at preserved stops
     + λ · Σ dropped_stops                 ← penalty for stops we can no longer serve
     + μ · Σ walking_time_to_mitigation    ← penalty for displaced riders
```

This is the central artifact. Other teams will optimize "shortest detour"; we optimize **"fewest broken promises to riders."** The three alternatives surfaced per line are the top picks across this cost.

## Locked decisions (from the grilling session, 2026-05-29)

| # | Decision | Rationale |
|---|---|---|
| **1. Closure UX** | Polygon draw in v1; snap-to-road in phase 2. | Polygon ships fastest, covers the preset-event story directly. Road-click is the bigger UX moment but defers without blocking. |
| **2. Routing engine** | **Valhalla** (Docker, Oberpfalz PBF). | Only OSS engine with **per-request `exclude_polygons`** — OSRM would need a graph rebuild per scenario (5–10 min), incompatible with the "click → reroute" pitch. |
| **3. Backend stack** | **FastAPI** in `backend/` (uv-managed), auto-generated typed TS client via `@hey-api/openapi-ts`. No auth — local demo only. | Lets us reuse the Python analysis pipeline (polars / shapely) at request time, instead of porting to TS. tRPC stack in `frontend/` deferred — `frontend/` continues to exist but uses generated client for backend calls. |
| **4. Reroute model** | For each affected line: walk stop sequence, find **last-served stop before zone** + **first-resume stop after zone**, route between them with `avoid_polygons`. Stops inside polygon are *dropped* (counted in cost). | Matches RVV operator's mental model: bus skips the closed area, resumes on the far side. Realistic and demoable. |
| **5. Alternative semantics** | **Hybrid:** vary the candidate resume stop (next 1–3 stops after closure) *and* request Valhalla geometry alternates per candidate. Rank by cost function. Return top 3. | Each alternative is now a distinct operator philosophy ("preserve timetable" vs "preserve stops" vs "shortest detour"). This is where the cost function earns its keep. Pure Valhalla-alternates would feel interchangeable. |
| **6. Compute timing** | **Eager** — single `POST /reroute` on polygon submit, computes everything for all affected lines + alternatives. | ~1.5s for ~4 lines × 3 candidates × 3 alts at ~100ms/route. Then every sidebar click is instant. Keeps demo rhythm tight. |
| **7. Time semantics** | v1: one **representative trip per (line, direction)** baked into `lines.parquet` — median-runtime trip departing closest to 14:00. v1.5 follow-up: operator picks from 3 candidates (morning / midday / evening). | Demo says *"at 14:23 the bus would be 47s late at Albertstraße"* — concrete and live. Skipping time entirely (D in the grilling) was rejected because it reduces us to shortest-detour, which is every other team's tool. |
| **8. Data ownership** | **Backend owns GTFS.** No client-side spatial math. | One source of truth; shapely STRtree on backend means point-in-polygon over 660 stops in microseconds. Frontend stays dumb: send polygon, render features. |
| **9. Persistence** | None for v1. Closures are ephemeral per request. No exclusion-zones DB table. | Local demo, no auth, no need. Drizzle/Postgres scaffolding in `frontend/` stays unused for now. |

## Data layer (the contract)

Two parquets, produced by a new `analysis/pipeline/build_schedule.py`, consumed by the backend at startup.

### `analysis/data/parquet/lines.parquet`
One row per (line, direction). ~94 rows.

| column | type | notes |
|---|---|---|
| `line_id` | str | `"1"`, `"C2"`, `"N3"` — matches OSM ref tag |
| `direction_id` | i8 | 0 / 1 |
| `line_name` | str | human-readable (from `Linien_Erklärung.pdf` extraction or short_name fallback) |
| `colour` | str | OSM `colour` tag for map styling |
| `geometry` | str | GeoJSON LineString — **canonical OSM variant** per (line, direction), picked by max GTFS-stop overlap, fallback longest polyline |
| `representative_trip_id` | str | one trip_id per (line, direction); median runtime, ~14:00 departure |
| `stop_sequence` | list[str] | ordered DHIDs for this direction |
| `candidate_trip_ids` | list[str] | optional: 3 trips (morning / midday / evening) for v1.5 operator selection |

### `analysis/data/parquet/stop_times.parquet`
One row per (representative_trip, stop). ~3,500 rows. Denormalises `stop_name`, `lat`, `lon` for hot-path access.

| column | type | notes |
|---|---|---|
| `trip_id` | str | |
| `line_id` | str | |
| `direction_id` | i8 | |
| `stop_seq` | i16 | order within trip |
| `stop_id` | str | DHID |
| `stop_name` | str | denormalised |
| `lat`, `lon` | f64 | denormalised |
| `arr_s` | i32 | seconds since service-day midnight (handles 25:30) |
| `dep_s` | i32 | |

### Backend startup (`backend/app/data.py`)
- `polars.read_parquet` → in-memory dicts: `lines_by_id`, `trip_stops`, `stops_by_id`
- `shapely.STRtree` over stop points → point-in-polygon ops in µs

## Architecture

```
analysis/pipeline/build_schedule.py     ← produces lines.parquet + stop_times.parquet
                  │
                  ▼
backend/   (FastAPI, uv)                 ← loads parquets, holds STRtree, proxies Valhalla
  GET  /lines                            ← all lines metadata + geometry for base layer
  POST /reroute  { polygon }             ← the demo endpoint (eager, returns full payload)
                  │
                  ▼
frontend/  (TanStack Start, Vite)        ← MapLibre + OSM raster + terra-draw polygon
  generated TS client from /openapi.json
                  │
                  ▼
Valhalla Docker (Oberpfalz PBF, port 8002)
```

## Build order (matches current task list)

1. `analysis/pipeline/build_schedule.py` → produces both parquets
2. `backend/` FastAPI scaffold (in progress) — rewrite models to `/reroute` shape
3. Backend GTFS loader + STRtree (`backend/app/data.py`)
4. Valhalla docker-compose at repo root
5. `GET /lines` endpoint
6. `POST /reroute` endpoint (the heart)
7. OpenAPI → TS client generation (`pnpm gen:api`)
8. MapLibre + terra-draw + sidebar UI

## Demo scenario

**Headliner: Bürgerfest weekend** — Altstadt polygon covering blocked streets. Lines 1, 6, A, C2 affected. Sidebar lists all four. Click Line 1: see original (gray) + polygon (red) + three alternatives — one preserves timetable best, one preserves stops best, one is shortest. Operator picks.

**Fallback:** Christkindlmarkt (Dec 2024) or June 2024 flood (more dramatic).

## What this is NOT

- Not a dispatcher / operator dashboard. (Every other team will build that.)
- Not a passenger-counting tool. (We have no APC data.)
- Not snap-to-road in v1 — polygon only. Snap-to-road is phase 2.
- Not deployable — local demo only.
- Not drone-related (separate project, see CLAUDE.md scope note).

## Open items (deferred, not blocking v1)

- **Cost-function tuning** — λ and μ start at 1.0; can be tuned with judges if asked.
- **Walking-to-mitigation calculation** — for each dropped stop, nearest reachable substitute. Currently placeholder; layer in if time.
- **Snap-to-road interaction (phase 2)** — single-click closes one edge; two-click stretches close a run.
- **Aug 2025 GTFS feed** — regional routes (route IDs `gfn-*`) not in v1; July city feed only.
- **Linien_Erklärung.pdf extraction** — better `line_name` than GTFS short_name. Nice-to-have.
- **Backend → Postgres** for saved scenarios (currently in-memory ephemeral). Out of v1 scope.
