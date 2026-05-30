# Omnibus — Plan

> **Pitch:** *"Every RVV bus is already a demand sensor. We mine a year of dwell-time telemetry to build a live demand map of Regensburg, then redeploy the* ***existing*** *fleet's idle hours to the demand pulses the fixed timetable misses — same buses, same drivers, smarter where-and-when."*

> Supersedes the reroute-on-closure plan (now [`PLAN_ARCHIVE_reroute.md`](./PLAN_ARCHIVE_reroute.md), kept as B-plan). Same `analysis/` pipeline feeds both.

---

## The problem

RVV runs a fixed timetable sized for the morning peak. Off-peak, that same fleet is over-served on some corridors and absent on others. Demand in a city *moves* through the day — residential → campus in the morning, campus ↔ campus midday, business parks → home at shift-end — but the timetable is static. The result: buses run near-empty on one line while real, recurring demand pulses elsewhere go unserved.

Nobody at RVV can see this movement, because **there is no passenger-count data** (APC exists internally but wasn't shared). So the demand is invisible and the slack is unquantified.

## The core insight (why this is technically credible)

We don't need passenger counts. **Dwell time is a demand proxy we already have:**

- `dwell_s = ts_departure_actual_door − ts_arrival_actual_door` → longer dwell ≈ more boarding/alighting.
- `door_opened` flag filters phantom stops (doors never opened → nobody waiting).
- Aggregated over a **full year** to a space-time grid `(stop × hour × day-of-week)`, noise averages out into a stable demand surface.

And we can quantify the slack we'd reallocate, also from data we have:

- `vehicle_block` (Umlauf) gaps = buses sitting idle between duties. Summed across the fleet midday, that's the reallocatable capacity — **a hard number, not a slogan.**

This pairing — *demand inferred from dwell* + *slack inferred from idle blocks* — is the project's IP. Everything else is presentation.

## What we're building

A web app: **a demand digital-twin of Regensburg that proposes flex deployments.**

1. Map of Regensburg, stops from GTFS.
2. A **time slider** (hour × day-of-week). As you scrub, a demand heatmap animates — you literally watch the city breathe.
3. As recurring **demand pulses** surface (e.g. OTH↔UR at lecture-block ends, a business park at 16:30 shift-end), the system pops a **flex-route proposal**: which idle bus is nearby, the route it would run, and the estimated riders served.

## Scope (locked)

Build **layers 1 + 4**. Flex routes are **pre-computed**, not solved live.

| # | Layer | Status |
| - | ----- | ------ |
| **1** | **Demand engine** — dwell → demand_proxy per `(stop × hour × dow)`, joined with weather / holidays / university_calendar / events; quantify idle `vehicle_block` slack | **build** |
| 2 | Pulse / OD detection — find recurring under-served pulses | light heuristic feeding the pre-compute |
| 3 | Live router | **skip** — see below |
| **4** | **Map UI** — Regensburg map, demand heatmap, time slider, baked flex-route proposals appearing on scrub | **build** |

### Why pre-computed routes (not live)
- Routing is a solved OSRM call — **not our innovation.** Don't spend demo-risk budget there.
- Flex transit plans the *next* service window from historical demand anyway — so pre-computed **is** the production model. Honest to say so on stage.
- Lets us curate the 3–4 *most compelling* examples (clear pulse, obvious idle bus, big rider win) instead of gambling on a live solver.
- Make the *map* feel live (smooth scrub, proposals appear in real time); the data underneath is baked.
- If asked "is it live?": *"Routing is standard OSRM. The intelligence is the demand model — that's what runs on RVV's live feed."*

## What this is NOT

- Not a dispatcher / operator dashboard — every other team builds that.
- Not real-time live rerouting — flex windows are planned ahead, by design.
- Not a passenger-counting tool — we have no APC; dwell-as-proxy is the whole point, and it's honest.
- Not the reroute-on-closure app (that's the archived B-plan).
- Not drone-related (separate project, see CLAUDE.md scope note).

## Why this wins on the criteria

- **Regensburg Factor:** real campuses (OTH, UR), real business parks, real event egress — pulses pulled from the actual RVV year.
- **Innovation:** inferring demand from dwell with zero new sensors, and reallocating measured fleet slack instead of buying vehicles.
- **Impact:** deployable on RVV's existing telemetry tomorrow; the slack number makes the savings concrete.
- **UI/UX:** one map, one slider. The city breathing is the entire interface.
- **Presentation:** scrub to 16:30 → red bloom over a business park → "Idle bus #1142, 8 min away → flex route, ~34 riders." That single interaction sells it.

## Demo moment

Drag the slider across a weekday. Judges watch demand flow residential→campus (AM), campus↔campus (midday), business→home (PM). At each pulse, a flex proposal draws itself on the map with an idle-bus match and a rider estimate.

## Architecture

- **Data / demand engine:** Python under `analysis/pipeline/`, polars. Reuses existing parquets (`stops_geo`, `stop_times`, `lines`, `features`, weather / holidays / university_calendar / events). Output: a compact demand-surface artifact + baked flex-route GeoJSON the frontend loads directly.
- **Backend:** `backend/` (Python app scaffolded) — thin; may not even be needed if the frontend reads static artifacts.
- **Frontend:** `frontend/` — TanStack Start + Vite, deploys to Cloudflare. Map + time slider + heatmap + route overlays.

## Build order

1. **Demand engine** → demand_proxy grid (`stop × hour × dow`) from dwell, enriched.
2. **Slack quantification** → idle `vehicle_block` windows, the headline number.
3. **Pulse pick + pre-compute** → choose 3–4 compelling pulses, match idle blocks, run OSRM once, freeze routes to GeoJSON.
4. **Map UI** → load artifacts, slider-driven heatmap, proposals on scrub.

## Open decisions (deferred)

- Exact demand_proxy normalization (raw dwell vs. dwell-per-stop-baseline z-score).
- Heatmap rendering approach (stop-point intensity vs. interpolated surface).
- Which 3–4 pulses headline the demo.
- Team split — who owns engine vs. UI.

## What we keep from prior data work

The whole `analysis/` pipeline is unchanged and central now: dwell/delay parquets are the demand signal; events / holidays / university_calendar explain *why* pulses occur (and let us caption proposals: "lecture block ends," "Jahn home game egress").
