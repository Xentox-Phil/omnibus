# Omnibus — Hackaburg 2026 Plan

**Team:** 5 people
**Dataset:** RVV / Air Fao ITCS data (multi-week, multi-event)
**Two deliverables:**
1. **Daytime fleet allocation optimizer** — fixed routes, optimize bus type + count per line per time window, informed by weather + events. Includes weather-aware delay prediction.
2. **Night on-demand booking system** — after ~20:00, scheduled service replaced by bookable rides. Vehicles pool riders, route dynamically.

**Rider surfaces:** mobile app + station kiosk (both can book + see ETAs).
**Operator surface:** dispatcher / fleet-allocation dashboard.

---

## Hour-1 contracts (do this together, 30 min, before anyone codes)

### 1. Shared stop catalog
File: `data/stops.csv`
Columns: `stop_id, name, lat, lng, line_ids` (which lines serve it)
Source: RVV GTFS feed (search "RVV Regensburg GTFS" — gtfs.de, transit.land, or RVV open data)
**Without this, persons 4 and 5 are blocked.**

### 2. Cleaned data parquet
File: `data/itcs.parquet` (Person 1 ships by hour 4)
Schema:
```
ts_arrival_actual   datetime
ts_arrival_planned  datetime
ts_departure_actual datetime
ts_departure_planned datetime
dwell_s             int        # departure_actual - arrival_actual (door)
delay_arr_s         int        # arrival_actual - arrival_planned
delay_dep_s         int        # departure_actual - departure_planned
productive_arr      bool
productive_dep      bool
line                string
direction           string
stop_id             string
trip_id             string     # synthetic if needed
distance_cum_m      int
event_tag           enum       # normal | flood | market | semester_start | uni_only
```

### 3. Weather parquet
File: `data/weather.parquet`
Source: **Open-Meteo historical API** (no key, free, JSON) or **DWD station Regensburg (03379)**.
Columns: `ts_hour, temp_c, precip_mm, wind_ms, humidity, weather_code`
Joined to ITCS by hour.

### 4. API contract (write OpenAPI/markdown first → mock immediately → frontends unblocked)

```
GET  /eta?line=&stop=&direction=
     → { eta_iso, scheduled_iso, delay_s, confidence, reason_codes: [...] }

GET  /allocation?date=&weather_scenario=&event=
     → { line_id: { hour: { bus_type, count } } }

POST /night/bookings
     body: { from_stop, to_stop, pax, requested_pickup_iso }
     → { booking_id, pickup_eta_iso, dropoff_eta_iso, vehicle_id, status }

GET  /night/bookings/:id
     → { ...booking, vehicle_position: {lat,lng}, current_status }

WS   /night/stream
     → realtime { vehicle_id, lat, lng, route_polyline, next_pickup, next_dropoff }
```

### 5. Repo + infra
- Monorepo: `data/`, `services/api/`, `services/ml/`, `services/dispatch/`, `apps/mobile/`, `apps/kiosk/`, `apps/operator/`
- Backend deploy: Fly.io or Render (single Dockerfile)
- Mobile: Expo dev build (QR code for judges)
- Web apps: Vercel

---

## Role allocation summary

| # | Role | Owns | Ships by demo |
|---|------|------|---------------|
| 1 | **Data + Evidence** | Cleanup, weather join, pitch charts | Parquet (4h), 3 hero charts, training-ready tables |
| 2 | **ML / Prediction** | Delay model, demand model, `/eta` API | Two models in production, weather-aware |
| 3 | **Fleet Optimizer** | Daytime allocation, operator dashboard | `/allocation` + interactive what-if UI |
| 4 | **Night Dispatch Backend** | Booking API, routing, pooling, vehicle sim | `/night/bookings` + live map stream |
| 5 | **Frontend (Mobile + Kiosk)** | Rider apps | Mobile app + station kiosk, both polished |

---

## Person 1 — Data + Evidence

**Mission:** team's data plumber + supplier of pitch ammunition.

### Timeline
- **H+0–4:** Parse all CSVs (UTF-16 encoded!), normalize columns, add `event_tag`, compute `dwell_s` and delays. Output `data/itcs.parquet`.
- **H+4–6:** Pull weather (Open-Meteo) for each file's date range. Output `data/weather.parquet`. Build join key.
- **H+6–10:** Three demo-grade charts:
  1. **Productive-stop rate by hour** — proves night waste (target: ≥30% of night stops are non-productive)
  2. **Delay distribution vs precipitation** — proves weather signal exists
  3. **Hochwasser week vs baseline week per-line delay** — proves event impact magnitude
- **H+10–24:** Build training tables for #2:
   - `delay_training.parquet` — one row per (trip, stop), with all features
   - `demand_training.parquet` — aggregated boardings-proxy per (stop, hour, weekday, weather)
- **H+24–end:** Iterate charts for pitch deck, support team with ad-hoc queries.

### Stack
Python, polars (faster than pandas for this size), matplotlib + plotly.

### Snippets
```python
import polars as pl
df = pl.read_csv("Hackaburg_2026/06.10.2024_19.10.2024_ITCS.csv", encoding="utf-16")
# parse dates: format "%d.%m.%Y %H:%M:%S"
```

---

## Person 2 — ML / Prediction (EXPANDED)

**Mission:** two production models behind APIs. Both are weather-aware. Both feed downstream consumers.

### Model A: Delay Prediction

**Purpose:** Given a bus currently running, predict delay at upcoming stops. Powers `/eta` for both rider apps.

**Problem framing**
- Regression target: `delay_s_at_stop_N+k` where k ∈ {1, 3, 5}
- Train per-k models (3 LightGBM models) OR a single multi-output model. Start with k=3 only for MVP, add others if time.

**Features (in order of expected importance)**
| Feature | Why it matters | Source |
|---|---|---|
| `current_delay_s` | strongest predictor — delay propagates | ITCS row |
| `delay_trend_last_3_stops` | accelerating vs recovering | derived |
| `hour_of_day` (cyclical: sin/cos) | rush hour effects | timestamp |
| `weekday` (one-hot) | weekend ≠ weekday | timestamp |
| `line_id` (one-hot or target-encoded) | line-specific characteristics | ITCS |
| `direction` | inbound vs outbound asymmetry | ITCS |
| `stop_id` (target-encoded by historical delay) | some stops always slow | ITCS |
| `dist_to_terminus_m` | slack absorption near terminus | derived from `distance_cum_m` |
| `dwell_avg_at_this_stop` | demand baseline | aggregated |
| `precip_mm_last_hour` | rain → slower | weather join |
| `precip_mm_now` | rain → slower | weather join |
| `temp_c` | extreme cold/heat → delays | weather join |
| `wind_ms` | high wind affects driving | weather join |
| `is_snow_or_ice` (derived from weather_code) | major slowdown | weather join |
| `event_tag` | flood / market / normal | dataset metadata |
| `school_holiday` (bool) | derived from Bavarian school calendar | external |
| `is_inbound_peak` | morning inbound / evening outbound | derived |

**Model**
- LightGBM regressor with quantile loss for prediction intervals (P10/P50/P90 → use P50 as ETA, P90-P10 as `confidence`)
- Train/val/test split: time-based (train on early data, test on last 3 days of each file)
- Evaluation: MAE in seconds, plus MAE bucketed by hour and by weather condition (must be robust under rain/snow)
- Target MAE: <60s for k=3, <120s for k=5

**API**
```python
@app.get("/eta")
def eta(line: str, stop: str, direction: str):
    # 1. Find the currently-running trip serving this (line, direction) approaching `stop`
    # 2. Pull its current_delay, dwell_trend, distance_to_stop
    # 3. Pull current weather (Open-Meteo current API)
    # 4. Predict → return {eta, delay, confidence, reason_codes}
```

**Reason codes** (for the kiosk UI: "delayed 4 min — heavy rain"):
- Compute SHAP values, return top 2 positive contributors as human strings
- Map: `precip_mm_now > 2` → "rain", `event_tag=flood` → "flood detour", `current_delay_s > 300` → "upstream delay", etc.

**Fallback model:** historical median delay for (line, stop, hour, weekday) bucket. If LightGBM API down, serve this.

### Model B: Demand Prediction

**Purpose:** Predict expected passenger demand (proxy: dwell-derived) per stop/line/hour given weather + day. Feeds **#3's optimizer** (daytime) and **#4's vehicle positioning** (night).

**Problem framing**
- Target: `expected_boardings_per_hour` at each (stop, hour, weekday, weather_bucket)
- Boardings unknown → use proxy: `boardings_proxy = max(0, dwell_s - baseline_dwell_s) / seconds_per_pax`
  - `baseline_dwell_s` = median dwell at that stop in low-demand hours (e.g., 02:00–04:00)
  - `seconds_per_pax` ≈ 1.5s (literature for European low-floor buses, calibrate later)
  - Clamp to reasonable bounds (0–60 pax)
- Aggregate to `(line, stop, hour, weekday, weather_bucket) → mean(boardings_proxy)`

**Features**
- `hour`, `weekday`, `line`, `stop_id`, `month`, `is_holiday`
- `temp_c`, `precip_mm`, `wind_ms`
- `event_active` (market, flood, semester start)
- `days_since_event_start` (for semester ramp)

**Model**
- Gradient boosting (LightGBM) per zone (night) and per line (daytime)
- OR simpler: hierarchical aggregation `(weekday, hour, weather_bucket) → demand` from history (no ML needed for MVP). Use ML only if time.

**Night zone clustering**
- For #4: cluster all stops into 5-8 zones using K-means on `(lat, lng)` weighted by mean nighttime demand
- Output: `data/night_zones.json` → `{zone_id: {center, member_stop_ids, predicted_hourly_demand}}`

**Outputs to consumers**
```python
# For #3's optimizer:
GET /demand?line=&date=&weather=
→ { hour: expected_pax }

# For #4's dispatch:
GET /night-demand?zone=&hour=
→ { expected_requests, suggested_vehicles }
```

### Model C (stretch) — Bunching Detector

**Purpose:** Identify trips at risk of bunching (catching up to leader) → operator can intervene (hold at stop).

- Binary classifier: will headway to leading bus drop below 50% of scheduled in next 10 min?
- Features: current headway, both buses' delays, dwell trend, weather
- Only if time after A + B are solid

### Model D (stretch) — Weather-conditioned schedule realism

- Per (line, stop, hour, weather_bucket): planned vs actual travel time → suggest schedule edits
- Output as a CSV deliverable for RVV
- "Sellable artifact" beyond the demo

### Stack
Python, LightGBM, scikit-learn, FastAPI, SHAP (for explanations), Open-Meteo client.

### Risks
- **Data leakage from `event_tag`** in production: at inference, you know weather but you don't know "flood" unless it's currently happening. For training, fine. For demo, set event manually via API param.
- **Cold-start stops** with little data → fall back to line-level averages.
- **Weather forecast vs observation**: train on observed, infer on forecast → distribution shift. Acceptable for hackathon.

---

## Person 3 — Fleet Optimizer + Operator Dashboard

**Mission:** "Given tomorrow's weather and events, here is the bus allocation."

### Timeline
- **H+0–4:** Define bus types. Make up reasonable numbers — judges won't audit, but be plausible.
  ```
  small    : capacity 25, cost/h €60,  CO2/km 800g
  midi     : capacity 45, cost/h €75,  CO2/km 1100g
  standard : capacity 80, cost/h €90,  CO2/km 1300g
  articul. : capacity 130, cost/h €110, CO2/km 1500g
  electric : capacity 80, cost/h €100, CO2/km 0g (charging windows!)
  ```
- **H+4–12:** Optimizer.
  - **Inputs:** demand per line per hour (from #2), bus type table, fleet size constraint per type, min frequency constraint per line
  - **Decision variables:** `x[line, hour, bus_type] = count`
  - **Objective:** minimize `Σ cost_per_hour * count + λ * max(0, demand - capacity)` (penalize under-capacity heavily)
  - **Constraints:**
    - `Σ_type capacity * count ≥ min_capacity_per_hour[line]`
    - `Σ_line count[line, hour, type] ≤ fleet_size[type]`
    - `Σ_type count[line, hour, type] ≥ min_buses_per_hour[line]` (frequency)
  - **Solver:** PuLP with CBC (free, bundled) for ILP. Or greedy heuristic if LP too slow.
- **H+12–22:** Operator dashboard (Next.js + Tailwind + Recharts):
  - Today's allocation: Gantt-style per-line per-hour chart with bus icons
  - Sliders / toggles: precipitation level, temperature, event picker (market / flood / normal / Friday game day)
  - **"Recalculate" button** → re-runs optimizer in <2s → shows new allocation + delta (€ saved, CO2 saved, capacity coverage)
  - Side-by-side: current static schedule vs optimized → big numbers
- **H+22–end:** Polish, demo scenarios pre-loaded.

### Stack
Python (PuLP + FastAPI) for optimizer, Next.js + Tailwind + Recharts for dashboard.

### Demo trick
Pre-script three "scenarios" with one-click buttons: **Sunny Wednesday**, **Rainy Friday + Christkindlmarkt**, **Snow + Hochwasser**. Each one re-runs the optimizer live → judges see the system reacting.

---

## Person 4 — Night On-Demand Dispatch

**Mission:** Working booking + dispatch demo with pooled rides.

### Timeline
- **H+0–3:** Data model + state store (SQLite or in-memory):
  - `Vehicle(id, type, capacity, current_lat, current_lng, current_route, onboard_pax)`
  - `Booking(id, from_stop, to_stop, pax, requested_pickup, status, vehicle_id, pickup_eta, dropoff_eta)`
  - `Stop` (from shared catalog)
- **H+3–10:** Matching / insertion algorithm:
  - **Algorithm:** greedy insertion (industry standard for hackathon-scale DARP)
    1. For incoming request `r`, for each vehicle `v`:
       - Try inserting pickup and dropoff into `v`'s current route at every valid position pair
       - Compute added time, check constraints (capacity never exceeded; no onboard pax detoured beyond max_detour_ratio = 1.5; pickup within deadline = requested + 10 min)
       - Record best feasible insertion cost
    2. Assign `r` to vehicle with lowest cost
    3. If no vehicle feasible → dispatch a new vehicle from depot OR reject
  - **Routing:** use OSRM public demo (https://router.project-osrm.org) for travel times, or local docker
- **H+10–16:** Vehicle simulator:
  - Tick every 5s
  - Each vehicle advances along its assigned polyline at the OSRM-given speed
  - Broadcast vehicle states over WebSocket
  - Mark pickups/dropoffs as they happen
- **H+16–22:** Hardening:
  - ETA accuracy (re-query OSRM as route updates)
  - Booking API with proper status transitions: `requested → assigned → en_route_pickup → onboard → completed`
  - Minimal admin map page (for debugging + pitch backup)
- **H+22–end:** Pre-load demo scenario: 10 requests over 30 sim-minutes, geographically spread, showing pooling in action.

### Stack
Python FastAPI + websockets, OSRM, SQLite, Leaflet for admin.

### Algorithm details (Greedy Insertion for DARP)
```
def insert(vehicle, request):
    best_cost = inf
    best_insertion = None
    route = vehicle.route  # list of (stop, op) ops
    for i in range(len(route) + 1):       # pickup position
        for j in range(i, len(route) + 1): # dropoff position (must be after pickup)
            new_route = route[:i] + [(request.from_stop, 'pickup', request)] + \
                        route[i:j] + [(request.to_stop, 'dropoff', request)] + \
                        route[j:]
            if not feasible(new_route, vehicle.capacity):
                continue
            cost = compute_added_time(route, new_route)  # OSRM
            if cost < best_cost:
                best_cost = cost
                best_insertion = new_route
    return best_cost, best_insertion
```
Constraints:
- Capacity never exceeded at any point along `new_route`
- No onboard rider's total trip time exceeds `direct_time * 1.5`
- Pickup time within `requested_pickup + 10 min`

### Risks
- OSRM rate limit on public demo → host local OSRM (Regensburg .osm.pbf is <50MB)
- Route plot jitter in browser → simplify polylines client-side

---

## Person 5 — Frontend (Mobile + Kiosk)

**Mission:** two polished rider UIs. **This is what judges see most — invest in polish.**

### Timeline
- **H+0–2:** Wireframes for both. Lock down screens with team.
- **H+2–8:** Mobile app (Expo / React Native, or mobile-first PWA if no native skills):
  - **Home:** search line/stop → live ETAs from `/eta` with delay reasons ("4 min late · heavy rain")
  - **Book night ride:** from→to picker (use stop catalog), see fare estimate + pickup ETA, confirm
  - **Active ride:** live map showing vehicle approach, walking directions to pickup point
  - **My bookings:** history
- **H+8–16:** Station kiosk (web, large-touch, fullscreen, designed for 1080×1920 portrait kiosk):
  - **Departures board:** for this station, next 30 min of all lines with live ETAs + delay reasons
  - **Big "Book night ride" button** (visible after 20:00) → same booking flow as mobile
  - **Service alerts:** if event tag active ("Christkindlmarkt — expect delays on lines 1, 2, 4")
- **H+16–22:** Polish:
  - Real backend wiring
  - Loading states, error states, offline fallback
  - Map (Leaflet or Mapbox) polish, custom bus icons
  - Animations on ETA updates
- **H+22–end:** Rehearsal screenshots for slides.

### Critical: use MSW (Mock Service Worker) from H+2
Don't block on backend. Mock all 4 endpoints with realistic responses. Switch to real API at H+12.

### Stack
- Mobile: Expo + React Native + react-native-maps
- Kiosk: Next.js + Tailwind + Leaflet
- Shared: TanStack Query for API calls

---

## Sync rhythm

- **H+0:** 30-min kickoff to lock the 5 contracts (stops, parquet, weather, API, repo).
- **Every 6h:** 15-min standup. Status, blockers, next 6h.
- **H-8 (8h before demo):** Feature freeze. Bugfixes + pitch rehearsal only.
- **H-4:** Full dry run of the 4-min demo.
- **H-1:** Backup video of the live demo recorded.

---

## Demo flow (4 min, rehearse this end-to-end)

| Time | Who | What |
|------|-----|------|
| 0:00–0:45 | #1 | **Problem.** Three hero charts: night waste, weather signal, event impact. "Today RVV runs the same schedule on a 5°C sunny Wednesday as on a 22°C rainy Friday during Christkindlmarkt. We can do better." |
| 0:45–1:45 | #3 | **Daytime solution.** Open operator dashboard. Click "Rainy Friday + Christkindlmarkt" scenario. Optimizer re-runs live. Show allocation delta + €/CO2 saved counter. |
| 1:45–3:15 | #5 + #4 | **Night solution.** Open mobile app, book night ride from kiosk simultaneously. #4's map shows vehicle dispatching, picking up a second rider en route (pooling visible). ETAs update live. |
| 3:15–3:45 | #5 | Show station kiosk in a 5s "imagine this in every Regensburg station" shot. |
| 3:45–4:00 | #1 | **Close.** "€X saved per day, Y kg CO2 saved per day, Z% more night coverage." Thank you. |

---

## Top 5 risks + mitigations

1. **Stop catalog missing/wrong** → blocks #4 + #5. **Mitigation:** H+1 deadline, no exceptions. If GTFS unavailable, scrape RVV's stop pages.
2. **Real-time map jank in live demo** → **Mitigation:** pre-record 60s video of dispatch in motion. Play if live fails.
3. **Optimizer doesn't beat baseline** → embarrassing numbers. **Mitigation:** frame as "minimal-disruption plan" not "max savings". Always have a story.
4. **Weather API rate limit during demo** → **Mitigation:** cache aggressively. Hardcode demo-day weather in fallback.
5. **OSRM rate limit / latency** → **Mitigation:** local docker container with Regensburg extract.

---

## Deliverables checklist

- [ ] `data/itcs.parquet` (#1)
- [ ] `data/weather.parquet` (#1)
- [ ] `data/stops.csv` (team H+1)
- [ ] `data/night_zones.json` (#2)
- [ ] 3 hero charts in `docs/charts/` (#1)
- [ ] `services/ml/` — delay model + demand model + FastAPI (#2)
- [ ] `services/optimizer/` — PuLP optimizer + FastAPI (#3)
- [ ] `services/dispatch/` — booking + matching + simulator + WS (#4)
- [ ] `apps/operator/` — Next.js dashboard (#3)
- [ ] `apps/kiosk/` — Next.js station kiosk (#5)
- [ ] `apps/mobile/` — Expo app (#5)
- [ ] Pitch deck (10 slides max)
- [ ] Backup demo video
