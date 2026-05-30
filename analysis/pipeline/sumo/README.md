# SUMO bus replay

Replays a day of RVV bus service from the **flex-bus scenario GTFS** feed through
a [SUMO](https://eclipse.dev/sumo/) microscopic simulation, and exports per-bus
geo trajectories the web app animates on its sim clock.

This is the substrate for the demo's headline move: **a bus peeling off its line
to serve Jahn-matchday demand.** The scenario feed (`scenario_gtfs.zip`) is the
July RVV timetable plus two scripted **flex blocks** baked in as GTFS trips —
`subset_gtfs` keeps them, SUMO routes them on-street like any other bus, and the
frontend paints them in a loud magenta so they read as flex buses.

Each flex block (`block_id` `FLEX_10_xx`) is three trips that hand off to one
another: a **line-10** leg, an **OUT_OF_SERVICE** deadhead reposition, then a
**route-5 relief** leg into Jahnstadion / HBF.

## Why SUMO (and not just GTFS interpolation)

The feed's `shapes.txt` is empty, so there's no published geometry to interpolate
along. SUMO routes every trip over the real OSM road network, giving plausible
on-street motion — and, crucially, a live-controllable simulation we can divert
a vehicle in (via TraCI) for a future live-reroute scene.

## Pipeline

```
build_network.py      OSM bbox (osmGet) -> netconvert -> regensburg.net.xml.gz
subset_gtfs.py        scenario feed -> lines {1,3,5,X4} + FLEX_ blocks, window -> gtfs_subset_*.zip
import_pt.py          gtfs2pt.py: snap stops + route trips -> pt_*.add.xml
                       + _flex_merge: fold each FLEX_xx_yy block's 3 trip-vehicles
                         into one continuous SUMO vehicle (parked dwell at layover)
run_sim.py            sumo --fcd-output.geo -> fcd.xml.gz  (lon/lat per 3s)
export_trajectories.py  fcd + vehicle lines -> trajectories_<date>.json (flex tagged)
```

`gtfs2pt` emits one `<vehicle>` per GTFS trip and ignores `block_id`, so a flex
duty arrives as three unrelated SUMO vehicles with a multi-minute gap at the
layover — and the marker disappears. `_flex_merge.py` post-processes
`pt_vehicles.add.xml` to fold each block into one vehicle with a
`parking="true" until=<next-leg-depart>` dwell on the boundary edge (bridging
non-contiguous legs via `sumolib` shortest path). Decision record + trade-offs:
[`analysis/docs/FLEX_BLOCK_MERGE.md`](../../docs/FLEX_BLOCK_MERGE.md).

The scenario feed ships as `data/_originals/scenario_gtfs.zip` (gitignored, like
all of `data/`); `subset_gtfs` auto-unboxes it to `data/raw/gtfs_scenario/` on
first run, so `run_all.py` is self-contained.

Run it all (idempotent; `--force` to rebuild from the OSM download down):

```bash
cd analysis
uv run python pipeline/sumo/run_all.py
```

Everything is uv-managed — `eclipse-sumo` ships the binaries + tool scripts as a
wheel, so there's nothing to install system-wide and no `SUMO_HOME` to set
(`_sumo_env.py` points it at the wheel). No SUMO GUI / XQuartz needed; the
pipeline is headless.

## Performance / regen cost

A full `--force` rebuild is **~90 s** (excluding the one-time network build).
The cost is lopsided — measured on a 16-core machine:

| Step                     | Time   | Notes                                           |
| ------------------------ | ------ | ----------------------------------------------- |
| `subset_gtfs.py`         | ~0.4 s |                                                 |
| **`import_pt.py`**       | **~85 s** | **the bottleneck** — gtfs2pt route mapping   |
| `run_sim.py`             | ~4 s   | the actual SUMO simulation                       |
| `export_trajectories.py` | ~1 s   |                                                 |
| `build_network.py`       | one-off | external OSM download + netconvert             |

**The SUMO sim itself is only ~4 s.** The bottleneck is `import_pt`
(gtfs2pt.py), which map-matches every bus trip onto the road network in a
**serial, single-threaded pure-Python loop** (`sumolib.route.mapTrace` — a
Dijkstra with thousands of router calls per trace). It pins 1 of 16 cores and
**gtfs2pt exposes no `--threads`/`--jobs` flag**, so adding cores does nothing.

Key nuance: `import_pt` is idempotent and only needs rerunning when the **GTFS
feed or network changes**. Its output (`pt_*.add.xml`) is reusable — so
re-running just the sim (different window, future TraCI reroute) is the
`run_sim` + `export` path at **~5 s**, not 90 s. The 85 s is a build-time cost
paid once per feed, not part of the demo replay loop.

Speedups (deliberately **not** done — would mean forking the vendored
`gtfs2pt.py`, too risky to attempt pre-demo):
- Parallelize the per-trace mapping loop (traces are independent) → potentially
  ~8–10× → ~10 s. No flag exists; requires patching the SUMO tool.
- Trace dedup via `traceCache` (0 cacheHits on the current feed — trips with
  identical stop sequences would dedupe).
- Zero-risk lever: shrink the window / line set in `subset_gtfs.py` → fewer
  traces → linearly faster.

## Scope

- **Date:** 2025-07-28 (the demo matchday; kickoff 18:00). The scenario's
  `SCENARIO_SERVICE` runs only this date.
- **Lines:** 1, 3, 5, X4 — 3 & 5 serve Jahnstadion, 1 is the flagship corridor,
  X4 the express — **plus every `FLEX_` block** regardless of line (they ride
  routes 10 / OUT_OF_SERVICE / 5, so the line filter alone would drop them).
  No built-in line filter in gtfs2pt, so `subset_gtfs.py` pre-cuts the feed.
- **Window:** 10:00–21:00. Change `BEGIN`/`END` in `subset_gtfs.py` +
  `import_pt.py` + `run_sim.py` (and `subset_gtfs.LINES`) to retune coverage.

## Outputs

All under `analysis/data/sumo/` — **gitignored + regenerable** (covered by the
root `analysis/data/**` rule). Served by the backend at `GET /sim/{date}` and
consumed by the frontend `BusLayer`.

`trajectories_<date>.json`:

```jsonc
{
  "date": "2025-07-28", "begin": 36000, "end": 75597,
  "buses": [
    { "id": "...", "line": "3", "points": [[t, lon, lat, angle], ...] },
    // flex buses additionally carry their block + a flag:
    { "id": "FLEX_10_02", "line": "FLEX",
      "block": "FLEX_10_02", "flex": true, "points": [...] }
  ]
}
```

`t` = seconds since midnight; coords rounded to 5 dp (~1 m). Flex detection:
post-merge each block is one vehicle whose id IS the block id, and the
exporter's `FLEX_\d+_\d+` regex matches it. The frontend (`BusLayer`) colors
`flex` buses magenta with an extra glow ring, and a hover popup shows the flex
block id.

## Next: reroute (scripted, not yet built)

Replace `run_sim.py`'s plain `sumo` run with a TraCI loop (`traci` is already a
dep): at kickoff, pick one bus near Jahnstadion and `changeTarget` / `setRoute`
it onto the stadium leg, then return it — tagging it so the FCD/exporter can
flag `diverted: true` for the frontend to highlight.
