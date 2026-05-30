# Demand bucket schema (v1) — pressure + event-reason service

The contract for the day-ahead demand output. A colleague builds the flex-bus
scheduler + map against this. **Lock before changing — additive changes only.**

## What this service is

A **pressure + event-reason service**, nothing else. It emits, for one day, a
per-stop time series of *demand pressure* plus the *reason* (event) behind any
surge. It does **not** own topology: bus lines, stop coordinates, names, hubs
all live in the GTFS-owned `nodes_meta` reference and are joined by `stop_code`.

- **Pressure** = predicted total boarding-dwell **seconds** per stop per tick
  (a relative demand index, NOT passenger counts — we have no APC data).
  Source: the general-demand GBM (`train_demand_model.py`), which is trained
  **event-free** so the baseline is a clean "normal day" counterfactual.
- **Event component** = bumps added on top by the kernel (`apply_events`).

## Two layers, one sum

| layer | field | meaning |
| ----- | ----- | ------- |
| GBM baseline (event-free) | `baseline_s` | normal demand under that date's calendar/time |
| event kernel             | `event_s`    | sum of event bumps at this stop |
| total (what you display)  | `pressure_s` | `baseline_s + event_s` |

### Kernel = profile-driven directional curves (demo feed)

Events come from a **hardcoded demo feed** (`pipeline/demo_events.json`), not the
events parquet. Each event names an `event_type`; the curve library
(`pipeline/kernel_profiles.json`) maps that type to pressure curves.

A **directional** event (e.g. `sport_football`) emits, **per origin stop**, two
legs linked by a shared `event_id`:
- **inbound** — boards at the origin stop (HBF), flows `to` the `event_stop`,
  anchored to the game `start` (peaks ~1h before kickoff).
- **outbound** — boards at the `event_stop`, flows `to` that origin, anchored to
  the game `end` (peaks ~20min after the final whistle).

A **non-directional** event (`directional:false`) emits one `leg:"onsite"` curve
per origin (or the `event_stop`), `to:null`. Curves are `[offset_min, level]`
keypoints, linearly interpolated; per-leg peak = `multiplier × scale_s`.

### Input feed: `pipeline/demo_events.json`

Flat array; the kernel filters to the predicted day (derived from `start`).
**Display-only contract** for the frontend — author by hand/backend, the frontend
reads the *output*, not this. Deliberately minimal: `event_type` picks the curve
shape + timing from `kernel_profiles.json`; `start`/`end`/`event_stop` anchor it;
each origin carries a `multiplier` (the only intensity knob — crank a stop
up/down). No attendance or capacity math.

```jsonc
{
  "event_id": "jahn_demo_2025-07-28",
  "event_label": "Jahn Matchday (demo)",
  "event_type": "sport_football",                 // enum → key into kernel_profiles.json
  "start": "2025-07-28T18:00:00+02:00",           // ISO 8601 + offset; date derived from this
  "end":   "2025-07-28T20:00:00+02:00",
  "event_stop": "JAHN",                            // the single anchor stop (pressure flows to/from)
  "origins": [                                     // feeder stops; each → one inbound + one outbound leg
    { "stop": "HBF", "multiplier": 1.0 }           // peak_s = multiplier × scale_s
  ]
}
```

## File: `demand_<date>.json`

One file per predicted day.

```jsonc
{
  "date": "2025-10-18",        // ISO date this surface is for
  "resolution_min": 15,        // tick width in minutes
  "n_ticks": 96,               // ticks in the day (24*60 / resolution_min)
  "tick_times": ["00:00", "…", "23:45"],  // index -> "HH:MM" window start, length n_ticks
  "nodes": [
    {
      "stop_code": "JAHN",     // join key into nodes_meta (GTFS); the 294 known stops
      "lat": 49.010, "lon": 12.100,          // stop coords (for plotting)
      "pressure_s":    [/* … */ 1840 /* … */],  // absolute, length n_ticks
      "pressure_norm": [/* … */ 0.88 /* … */],  // 0–1, pressure_s / global max (heatmap color)
      "baseline_s":    [/* … */  240 /* … */],  // length n_ticks
      "event_s":       [/* … */ 1600 /* … */],  // length n_ticks
      "events": [              // events touching THIS stop; [] if none. They stack.
        {
          "event_id": "jahn_demo_2025-07-28",     // SAME id on both legs' stops = one event
          "event_label": "Jahn Matchday (demo)",
          "leg": "outbound",                      // "inbound" | "outbound" | "onsite"
          "to": "HBF",                            // destination stop this pressure flows to (null if onsite)
          "multiplier": 1.0,                      // this origin's intensity knob (peak_s = multiplier × scale_s)
          "active_ticks": [80, 81, 82, 83, 84, 85],
          "contribution_s": [/* … */ 1275 /* … */] // this event's share of event_s, length n_ticks
        }
      ]
    }
    // … all 294 stops, dense (every stop present every day), keyed by stop_code
  ]
}
```

## Invariants the consumer can rely on

- Every series array (`pressure_s`, `pressure_norm`, `baseline_s`, `event_s`,
  `contribution_s`) has length `n_ticks`, index = tick, aligned to `tick_times`.
- `baseline_s[t] + event_s[t] == pressure_s[t]` for all `t`.
- `event_s[t] == sum(events[*].contribution_s[t])` (handles two events on one stop).
- `event_s[t] > 0` ⟺ some `events[*]` has `t` in `active_ticks`; event-free
  stops have `event_s` all-zero and `events: []`.
- `pressure_norm[t] == pressure_s[t] / global_max` (0–1, normalized against the
  day's single global peak — comparable across stops; global_max is recoverable
  as `max(pressure_s)` over all nodes if the absolute scale is needed).
- `nodes` is dense: all 294 known stops present, keyed by `stop_code`, every day.
- Pressure unit = boarding-dwell **seconds** (relative index, not passengers).

## Companion file: `demand_<date>_events.json` (event-first curves)

The surface buries each event's curve inside 294 nodes. This companion is the
**inverse view** — event-first — so the frontend can draw arrival/departure
curves without scanning the surface. Sampled at **1-min** (the curve is analytic,
so fine sampling is free) and **windowed** to the active span. Each leg ships the
same curve twice: `pressure_s` (absolute boarding-dwell seconds) and
`pressure_norm` (0–1 vs that leg's own `peak_s`). Flat by design — no nesting.

```jsonc
{
  "date": "2025-07-28",
  "resolution_min": 1,                         // tick width; x-axis is implicit
  "events": [
    {
      "event_id": "jahn_demo_2025-07-28",
      "label": "Jahn Matchday (demo)",
      "type": "sport_football",                // key into kernel_profiles.json
      "venue": "JAHN",                         // the anchor stop (pressure flows to/from)
      "event_start": "18:00",                  // kickoff,  "HH:MM" local
      "event_end":   "20:00",                  // whistle,  "HH:MM" local
      "stops": ["HBF", "JAHN"],                // every stop with a curve here (map highlight)
      "legs": [
        {
          "from": "HBF", "to": "JAHN",         // directional flow; from→venue = inbound
          "start": "14:58",                    // pressure ramps up  "HH:MM"
          "end":   "18:23",                    // pressure dies out  "HH:MM"
          "peak_s": 2200.0,                    // absolute peak = max(pressure_s) = pressure_norm's 1.0
          "pressure_s":    [45.5, 47.6, /* … */, 49.0],   // absolute (boarding-dwell seconds)
          "pressure_norm": [0.0207, 0.0216, /* … */, 0.0223]  // same, normalized 0–1 vs peak_s
        }
        // … outbound JAHN→HBF (its own start/end), plus one leg-pair per extra origin
      ]
    }
  ]
}
```

A **leg** = one directional demand curve = one flex-bus run. A football match
makes two: `from`→`venue` (**inbound**, fans ride to the venue *before* kickoff)
and `venue`→`from` (**outbound**, ride back *after* the whistle). Each leg carries
its **own** pressure span.

- **x-axis is implicit**: `time[i] = leg.start + i * resolution_min`. No parallel
  `times` array — reconstruct it. `pressure_s[i]` / `pressure_norm[i]` are the y.
- **two curves, same shape**: `pressure_s` (seconds) and `pressure_norm` (0–1 vs the
  leg's `peak_s`). Recover one from the other: `pressure_s[i] == pressure_norm[i] * peak_s`.
  ⚠ `pressure_norm` here is per-leg (vs its own peak), NOT the surface's global-max norm.
- **4 timeline markers**: `event_start`/`event_end` (the match, event-level) and each
  leg's `start`/`end` (its pressure span). Draw them as vertical lines under the curve.
- `peak_time` is **not** shipped — it's `argmax(pressure_s)`, derive it if needed.
- `stops` = flat de-duped list of every leg's `from` → highlight these on the map.
- One `event_id` → all its legs in one object (vs. split across stops in the surface).
- Multi-origin → more legs. Match a curve to its surface bump by `(event_id, from, to)`.

## Boundary: what is NOT here

`lat`/`lon` are included for plotting convenience. The richer topology —
`stop_name`, `is_hub`, `lines`, `near_venue` — stays in **`nodes_meta`**
(GTFS-owned static reference), joined by `stop_code`. Topology changes on a
different clock than demand; mirroring all of it here would make it stale.

## Reading direction (for the flex scheduler)

Each event entry is a directed edge: **origin = the stop it sits on**,
**destination = `to`**, **magnitude = `contribution_s`**. So at tick `t`:
`HBF` with `leg:"inbound", to:"JAHN"` → run a flex bus HBF→Jahnstadion;
later `JAHN` with `leg:"outbound", to:"HBF"` → run it back. Match the two legs
by shared `event_id`.

## Forward-compatible (additive only)

- swap the hardcoded `demo_events.json` for a live feed (same event fields).
- `source` (`declared`/`predicted`) on events, once a second source exists.

Consumers reading only the documented fields keep working when these are added.
