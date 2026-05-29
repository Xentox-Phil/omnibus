# Omnibus — Plan

> **Frame:** RVV's data is about **buses and the city**, not passengers (no APC). Drop every angle that fakes demand from dwell time. Pitch: *"6 million km of moving sensors. What do they know about Regensburg?"*

One ingest pipeline + GTFS-snapped delay table → three scenes, one product.

```
parquet + GTFS-snapped delay table
        │
        ├── A: per road segment → infrastructure diagnostic
        ├── B: per (line, stop, hour) variance → reliability rec engine
        └── C: cross-line temporal correlation → contagion DAG
```

---

## Scene A — Regensburg Pulse (city-infrastructure diagnostic)

**One-liner:** Map of Regensburg ranked by which intersections/corridors silently destroy bus reliability.

**Compute:**
1. For each trip, sample `(delay_arr_s, distance_cum_m)` at every stop.
2. Diff consecutive stops → *delay added on that segment*.
3. Snap to OSM roads via GTFS shapes + map-matching (OSRM/Valhalla trace).
4. Aggregate over millions of trips → per-road-segment "delay productivity" with CIs.
5. Split chronic (consistent) vs acute (event-driven).

**Output:** ranked list addressed to the **city**, not RVV. e.g.
*"D.-Martin-Luther-Str. between Albertstr. and Königstr. costs the network 142 bus-hours/week between 7:30–9:00. Fix: signal pre-emption for Lines 6, 11, X4."*

**Risk:** map-matching is the time sink. Use GTFS shapes if RVV's feed includes them.

---

## Scene B — Reliability, not Speed

**One-liner:** Riders don't notice a bus always 4 min late. They notice the one that's sometimes on time and sometimes 12 min late. Optimize for **σ**, not mean.

**Compute:**
1. Per `(line, direction, stop, time-bucket)`: σ of `delay_arr_s` + 95–5 percentile spread.
2. Rank corridors by *unreliability*.
3. ML classifier: given a stop's variance profile, label the cause:
   - **Upstream propagation** (variance grows monotonically from terminal)
   - **Local bottleneck** (variance jumps at one stop, stays)
   - **Bunching** (variance correlated with previous bus headway)
   - **Weather-coupled** (variance explained by weather feature)
4. Each class → different intervention (buffer reallocation, holding point, terminal smoothing).

**Demo:** Line 6. Show published timetable vs real arrival distribution at 5 stops. Push "rewrite schedule" → re-simulate, gain X min of *trust* per rider per week.

**UI risk:** σ is not visually punchy. Use violin / fan charts, not bars.

---

## Scene C — How Regensburg Breaks (disruption autopsy)

**One-liner:** Replay the **June 2024 flood** and the **2024 Christmas market** through the network. Show one corridor failing poisoning the rest. Identify systemically fragile lines.

**Compute:**
1. Graph: nodes = stops, edges = scheduled trips, weight = delay.
2. Per 5-min window across flood/market weeks, compute delay field across graph.
3. Granger-style propagation: "Line A's delay at 08:15 predicts Line B's delay at 08:25 at shared stop X" → contagion DAG.
4. Rank by **out-degree** (breaks others) and **in-degree** (gets broken). Identify keystones.

**Demo segments:**
1. **Flood (2 June 2024)** — scrub timeline, watch inundated corridor go red, red leaks outward. Show recovery half-life.
2. **Market (Dec 2024)** — daily 17–19h pulse, where the system absorbs vs where it doesn't.
3. **Autopsy report** — "Line N is the keystone — when it fails, 4 lines lose >5 min/trip within 20 min. Hardening returns X bus-hours/week."

**Cheap fallback** if Granger is too much: cross-correlate delay time-series between line pairs, threshold the correlations, draw the DAG. Visually identical.

---

## Why this wins on the criteria

- **Tech difficulty:** map-matching + variance ML + graph contagion = three real systems.
- **Innovation:** nobody else will drop the passenger framing. Differentiated from the inevitable wall of dispatcher dashboards.
- **Impact:** A and C produce *concrete recommendations* (fix this intersection, harden this corridor). B produces a metric the field actually argues for.
- **UI/UX:** one shell, three scenes, scrubbable timelines, animated network. Story over chrome.
- **Presentation:** clean narrative arc — *city map → line-level truth → catastrophic week*. Ends on the flood. Memorable.

---

## What this does NOT include (deliberately)

- Passenger count inference from dwell time (circular, RVV judges will see through it).
- Operator/dispatcher console (every other team will build this).
- Anything drone- or hardware-related (separate project, see CLAUDE.md scope note).

## External data to join

**Must-add:**
- **Weather** — Open-Meteo historical, hourly. Pull `temp`, `precip`, `wind`, `visibility` for Regensburg (`lat=49.013, lng=12.101`). Required for B's weather-coupled variance class and for C's flood week to be more than a coincidence. Free, no key.
- **Bavarian school holidays** — static CSV. Half the 2024 baseline overlaps Herbstferien (28 Oct–2 Nov 2024); without it every Tuesday-morning pattern is contaminated.
- **University calendars (OTH + Uni Regensburg)** — semester start/end + lecture schedules, public. Turns the uni-lines dataset (23.04–09.05.2025) from "guess what's happening" into "correlate dwell spikes to actual lecture endings." Makes the uni slice the strongest sub-story.

**High-value:**
- **Event calendar** — Christmas market ✓, **Jahn Regensburg home games** (Continental Arena), **Dult** (Mai-/Herbstdult, 10-day folk festival), **Eisbären** ice hockey home games. For Scene C, a Dult or Jahn game is a cleaner "predictable surge" demo than the Christmas market (localised in time + space).
- **OSM POIs near stops** — hospitals, schools, malls, uni buildings. *Don't* use to predict demand (passenger-count trap). Use to *explain* Scene A's outputs: "this segment is hot because Klinikum entrance is here." Justification layer only.

**Skip:**
- Road closures / construction history — perfect for Scene A but Regensburg doesn't publish cleanly. Not worth a day of hunting.
- Mobile / Telefónica movement data — gold standard but not free, not in 2 days. Mention as "next step" in pitch.
- Traffic counts — coverage too patchy; bus delay variance is the better signal.
- Social media — too noisy, judges will ask.

## Open decisions

- Pick one scene to lead the demo with (current lean: open on **A**, deep-dive on **B**, finish on **C**).
- Person-by-person split — not yet drafted.
- Flood Meldestufe timeline already known: peak 02.06.24, Stufe 4, 5.5 m.
