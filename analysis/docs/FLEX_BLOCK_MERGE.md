# Flex-block merge — decision record

**Date:** 2026-05-30
**Status:** Implemented (`analysis/pipeline/sumo/_flex_merge.py`, wired into `import_pt.py`).

## Context

A flex duty is a single physical bus that performs three back-to-back GTFS
trips sharing a `block_id`:

1. A **line-10 leg** — the bus runs its regular line until the pull-off point.
2. An **OUT_OF_SERVICE deadhead** — repositioning toward the relief corridor
   (unboardable: `pickup_type=1, drop_off_type=1`).
3. A **relief leg** on an existing route (e.g. route 5 into Jahnstadion).

The flex recommendation engine writes the three trips with a shared `block_id`
(`FLEX_10_02`, `FLEX_10_05`) and a manifest describing the segments.

SUMO's `gtfs2pt` importer ignores `block_id`. It emits one `<vehicle>` per
GTFS trip — three unrelated vehicles per duty. For `FLEX_10_02` specifically,
the OUT_OF_SERVICE leg ends at 16:48 and the relief leg starts at 17:14, so
**no SUMO vehicle exists for that block during 26 minutes of layover**. The
trajectory exporter emits three separate trajectories and the frontend renders
three short-lived markers — the flex bus "disappears" at the layover and
"reappears" elsewhere as a fresh marker.

## Options considered

| Option | Where the fix lives | Verdict |
| --- | --- | --- |
| **A — Merge legs into one SUMO vehicle** | `import_pt.py` post-process | **Chosen.** Reality-matching: one physical bus, parked at layover. Gives TraCI a persistent vehicle id for the future live-reroute scene. |
| B — Chain at the GTFS layer | `flex_recommend.py` (one combined trip, deadhead rows unboardable) | Works but conflates the per-leg `route_id` identity in the GTFS feed itself; anyone reading the feed alone sees a hybrid trip. |
| C — TraCI handoff controller | New script wrapping `run_sim.py` | Doesn't solve the multi-id problem; the frontend would still need to stitch. Adds runtime complexity for no rendering gain. |
| Frontend stitch | `BusLayer.tsx` + `buses.ts` | Cheapest and demo-safe, but the simulation still models reality wrong (three vehicles for one bus), and TraCI sees three transient ids. |

## Decision: Option A

Post-process `pt_vehicles.add.xml` after `gtfs2pt` runs. For each flex block:

- Group vehicles by `block_id` (parsed from the `FLEX_xx_yy_…` id prefix).
- Build one continuous edge sequence from the per-leg routes. Where two legs
  share their boundary edge, dedup; where they don't, bridge with
  `sumolib.net.getShortestPath(..., vClass="bus")`.
- Concatenate the per-leg `<stop>` lists. On each inter-leg boundary, insert a
  `<stop ... parking="true" until="<next-leg-depart>"/>` on the boundary edge.
  The bus parks during the layover (no traffic interaction, stationary FCD
  points) and resumes when the relief leg's scheduled depart is reached.
- Replace the three per-leg `<vehicle>` + `<route>` entries with one merged
  `<vehicle id="FLEX_xx_yy">` referencing one merged `<route>`. The vehicle's
  `line` is set to `"FLEX"`; per-leg line identity (10 / OUT / 5) is no longer
  carried at the SUMO level — `scenario_manifest.json` already mirrors the
  segments for the UI.

The merged vehicle id (`FLEX_10_02`) still matches the trajectory exporter's
`FLEX_\d+_\d+` regex, so flex tagging in `trajectories_<date>.json` is
unchanged.

## Trade-offs

- **Per-leg `line` is lost in SUMO.** The merged vehicle's `line="FLEX"` does
  not carry route 10 / route 5 identity. The frontend already paints flex
  buses magenta regardless of `line`, so visually this is a no-op. If TraCI
  needs to know which segment a flex bus is currently on, query the merged
  route position against the manifest, not `traci.vehicle.getLine()`.
- **Schedule slack absorbs late arrival.** `until=<next-leg-depart>` means
  "leave no earlier than X." If the simulated leg N runs long and the bus
  arrives at the layover after X, the parking stop is a no-op and the bus
  immediately continues. The original 3-vehicle pipeline had the same property
  by construction (RELIEF was a separate vehicle that departed at its
  scheduled time regardless of where the OUT vehicle was).
- **SUMO warnings about `until=` values in the past.** gtfs2pt writes per-leg
  stop `until` values relative to that leg's depart (so they look like
  small numbers e.g. `until="360"`). In the merged vehicle they're way past
  the simulation clock by the time the bus arrives. SUMO warns and falls back
  to the stop's `duration="10"` — the intended behavior. Cosmetic only.
- **Rare teleport at the bridge.** On a bus-class shortest-path bridge, SUMO
  occasionally teleports the vehicle if it deadlocks at a junction (see
  `time-to-teleport="300"` in `sim.sumocfg`). The trajectory remains
  continuous; the visual blip is well within the layover window.

## Verifying the fix

```bash
cd analysis
uv run python pipeline/sumo/import_pt.py --force      # runs gtfs2pt + merge
uv run python pipeline/sumo/run_sim.py --force
uv run python pipeline/sumo/export_trajectories.py --force
```

Then:

```python
import json
d = json.load(open("data/sumo/trajectories_2025-07-28.json"))
for b in d["buses"]:
    if b.get("flex"):
        pts = b["points"]
        print(b["id"], len(pts), "pts",
              f'{pts[0][0]//3600:02d}:{(pts[0][0]%3600)//60:02d}',
              "->",
              f'{pts[-1][0]//3600:02d}:{(pts[-1][0]%3600)//60:02d}')
```

Expected: two flex buses (`FLEX_10_02`, `FLEX_10_05`), each one continuous
record spanning all three legs. For `FLEX_10_02`, points 16:48 → 17:14 cluster
tightly at the layover coordinates (parked).
