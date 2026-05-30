# Omnibus — Plan (ARCHIVED B-plan: reroute-on-closure)

> **Status:** Superseded 2026-05-29 by the demand-driven flex-routing plan in [`PLAN.md`](./PLAN.md). Kept as a fallback / idea bank. The `analysis/` data pipeline described here is unchanged and still feeds the active plan.

> **Pitch:** *"Click a street. We re-plan the network so the bus still shows up when the timetable says it will."*

---

## The problem

RVV operates in a city that constantly closes roads — construction, events (Bürgerfest, Dult, Christkindlmarkt, Jahn home games), floods. Every closure forces a manual reroute decision and silently strands stops. There is no tool that helps the operator pick the *best* reroute.

## What we're building

A web app where you:

1. Open a map of Regensburg.
2. Click road segments to mark them blocked — or pick a preset like *"Bürgerfest weekend"* or *"June 2024 flood"*.
3. Pick a time window.

The system responds with reroute proposals for every affected bus line. For each proposal it shows:

- the new route on the map,
- which stops are still served, and by how many seconds their arrival times shift vs the published timetable,
- which stops are dropped, and what to do about them (nearest reachable stop, shuttle, small detour),
- a single score saying how well the proposal preserves the published timetable.

## The metric we optimize

A reroute is good if **riders still get picked up close to when the timetable promised**.

Formally:

```
cost = Σ |t_new(stop) − t_planned(stop)|   ← deviation at preserved stops
     + λ · Σ dropped_stops                 ← penalty for stops we can no longer serve
     + μ · Σ walking_time_to_mitigation    ← penalty for displaced riders
```

This is the central artifact of the project. Everyone else will optimize "shortest detour"; we optimize **"fewest broken promises to riders."**

## What this is NOT

- Not a dispatcher / operator dashboard. (Every other team will build that.)
- Not a passenger-counting tool. (We have no APC data; faking it is circular.)
- Not the prior three-scene analytical story (Pulse / Reliability / Autopsy) — preserved in git history as a B-plan only.
- Not drone-related (separate project, see CLAUDE.md scope note).

## Why this wins on the criteria

- **Regensburg Factor:** every closure scenario in the demo is a real Regensburg event.
- **Innovation:** the metric is the innovation. "Preserve the timetable" is a different objective than anyone else will pick.
- **Impact:** plugs into a real RVV workflow — they make reroute decisions manually today.
- **UI/UX:** one map, one click, three proposals. No dashboard wall.
- **Presentation:** the live demo lands. Click a road → watch the network re-plan.

## Demo scenario

Headliner: **Bürgerfest weekend** — Altstadt closures, Lines 1 + 6 affected.
Fallback: **Christkindlmarkt** (Dec 2024) or the **June 2024 flood** if we want a more dramatic story.

---

## Open decisions (deferred — will be made together)

- Stack and architecture.
- Whether to add a high-fidelity traffic-simulation validator on top of routing estimates.
- Team split — who owns what.
- Final demo scenario (Bürgerfest is the current lean).

## What we keep from prior data work

The data pipeline under `analysis/` (events, holidays, weather, university calendars, RVV delays) is unchanged and feeds straight in — the events parquet, for example, drives the preset-closure dropdown.
