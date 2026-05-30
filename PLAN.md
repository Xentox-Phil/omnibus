# Omnibus — Plan (demand / flex-bus)

> **Pitch:** *"Every RVV bus is already a demand sensor. We mine a year of dwell-time
> telemetry into a day-ahead demand surface for Regensburg, then schedule on-demand
> flex buses to the recurring pulses — and the event spikes — the fixed timetable
> misses. Same fleet, smarter where-and-when."*

> **Pivot history:** This is the active direction. Earlier iterations under
> [`ideas/_archive/`](./ideas/_archive/):
> 1. `reroute-v1.md` — original three-scene analytical story. Discarded.
> 2. `demand-twin.md` — first demand digital-twin sketch. **This plan is its descendant**, advanced into a concrete day-ahead model + scheduler.
> 3. `reroute-v2.md` — reroute-on-closure with Valhalla. Built a backend scaffold, then set aside; kept as a possible B-plan.
>
> The `analysis/` data pipeline is shared across all iterations; nothing in there is wasted.

---

## The problem

RVV runs a fixed timetable sized for the morning peak. Off-peak, the same fleet is
over-served on some corridors and absent on others, and big **event egress** (Jahn home
games, Dult, Bürgerfest) overwhelms specific stops at predictable times. Demand *moves*
through the day; the timetable is static. Nobody at RVV can see the movement, because
**there is no passenger-count data** (APC exists internally but wasn't shared).

## The core insight (why this is technically credible)

We don't need passenger counts. **Dwell time is a demand proxy we already have:**

- `dwell_s = ts_departure_actual_door − ts_arrival_actual_door` → longer dwell ≈ more boarding.
- `door_opened` filters phantom stops (doors never opened → nobody waiting).
- Aggregated over a **full year** to `(stop × hour × day-of-week)`, noise averages into a
  stable demand surface.

Pressure unit = **boarding-dwell seconds** — a relative demand index, honest about having
no APC.

## What we're building

1. **Day-ahead demand surface** — for any date, a per-stop pressure series, split into a
   `baseline_s` (a clean "normal day") and an `event_s` bump, summed into `pressure_s`.
2. **Event demand curves** — per event, smooth per-minute pressure curves on the affected
   stops, directional (inbound to the venue pre-event, outbound after).
3. **Flex-bus scheduler** (colleague) — consumes the surface, matches idle capacity to the
   pulses, proposes on-demand routes.
4. **Map UI** — Regensburg map + demand heatmap over time + per-event curve charts +
   flex-route proposals.

## The data engine (built)

`analysis/pipeline/predict_demand.py` → two artifacts per date, both from one set of leg specs:

- **`demand_<date>.json`** — node-keyed **15-min** surface, 300 stops × 96 ticks:
  `baseline_s` (GBM, event-free) + `event_s` (kernel) = `pressure_s`, plus `pressure_norm`
  and per-stop `events[]`. The map/scheduler contract.
- **`demand_<date>_events.json`** — event-first **1-min** curve export: per event, one
  directional curve per leg (`from → to`), shipped as both `pressure_s` (seconds) and
  `pressure_norm` (0–1), windowed to its active span. The frontend curve charts.

**Contract:** [`analysis/docs/DEMAND_BUCKET_SCHEMA.md`](./analysis/docs/DEMAND_BUCKET_SCHEMA.md) — lock before changing; additive only.

### Two layers

| layer | source | meaning |
|---|---|---|
| `baseline_s` | GBM (`train_demand_model.py`), trained **event-free** | normal-day demand under the date's calendar/time |
| `event_s` | profile kernel reading `demo_events.json` + `kernel_profiles.json` | event bumps added on top |

### Event kernel
- Input feed: **`pipeline/demo_events.json`** (hardcoded demo, not the parquet). Each event
  names a `type`, `start`/`end`, `event_stop` (venue), and `origins` each with a `multiplier`
  (the only intensity knob — no attendance/cap math).
- Curve library: **`pipeline/kernel_profiles.json`** maps `event_type` → smooth
  double-logistic pulse (asymmetric rise/fall), `scale_s`, directional in/out keypoints.
- A directional event emits, **per origin**, an inbound leg (origin→venue, peaks pre-start)
  and an outbound leg (venue→origin, peaks post-end), linked by `event_id`.

## Architecture

```
analysis/pipeline/
  train_demand_model.py   ← GBM baseline (event-free), -> data/models/
  predict_demand.py       ← surface + event curves for a date -> data/demand/
  demo_events.json        ← hardcoded demo event feed
  kernel_profiles.json    ← event_type -> pressure-curve library
        │
        ▼  data/demand/demand_<date>.json + demand_<date>_events.json
backend/  (FastAPI, uv)    ← THIN dummy stub: GET /demand/{date}, /events/{date}
        │                    (frontend can also read the static files directly)
        ▼
frontend/                  ← map + demand heatmap over time + per-event curves + flex proposals
```

## Demo scenario

**Jahn matchday** (demo: 2025-07-28, kickoff 18:00). Scrub the day: baseline pulse, then
the event blooms — inbound HBF→Jahnstadion building before kickoff, outbound Jahnstadion→HBF
spiking after the whistle. The scheduler proposes flex buses onto those legs. Each event ships
clean per-minute curves the UI plots directly.

## What this is NOT

- Not a dispatcher / operator dashboard. (Every other team builds that.)
- Not a passenger-counting tool — we have no APC; dwell-as-proxy is the whole point.
- Not the reroute-on-closure app (archived B-plan, `ideas/_archive/reroute-v2.md`).
- Not real-time live solving — flex windows are planned day-ahead, by design.
- Not drone-related (separate project, see CLAUDE.md scope note).

## Open items

- **Inbound peak timing** — tune in `kernel_profiles.json` if it peaks too early.
- **`nodes_meta.json`** generator — `stop_name`/`is_hub`/`lines`/coords by `stop_code` (GTFS-owned
  topology the demand surface joins to). Scheduler + frontend need it.
- **Flex-bus scheduler** — consumes the surface; matches idle `vehicle_block` slack to pulses.
- **Frontend** — map heatmap, time scrub, per-event curve charts, flex-route overlays.
- **Backend** — currently a dummy stub; flesh out only if static files prove insufficient.
