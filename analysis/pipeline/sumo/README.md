# SUMO bus replay

Replays a day of RVV bus service from the **July GTFS** feed through a
[SUMO](https://eclipse.dev/sumo/) microscopic simulation, and exports per-bus
geo trajectories the web app animates on its sim clock.

This is the substrate for the demo's headline move: **one bus peeling off its
line to serve Jahn-matchday demand** (the reroute is scripted on top of this
replay — see *Next: reroute* below — SUMO replays the timetable, it doesn't
decide the diversion).

## Why SUMO (and not just GTFS interpolation)

The July `shapes.txt` is empty, so there's no published geometry to interpolate
along. SUMO routes every trip over the real OSM road network, giving plausible
on-street motion — and, crucially, a live-controllable simulation we can divert
a vehicle in (via TraCI) for the reroute scene.

## Pipeline

```
build_network.py      OSM bbox (osmGet) -> netconvert -> regensburg.net.xml.gz
subset_gtfs.py        July feed -> lines {1,3,5,X4}, match window -> gtfs_subset_*.zip
import_pt.py          gtfs2pt.py: snap stops + route trips -> pt_*.add.xml
run_sim.py            sumo --fcd-output.geo -> fcd.xml.gz  (lon/lat per 3s)
export_trajectories.py  fcd + vehicle lines -> trajectories_<date>.json
```

Run it all (idempotent; `--force` to rebuild from the OSM download down):

```bash
cd analysis
uv run python pipeline/sumo/run_all.py
```

Everything is uv-managed — `eclipse-sumo` ships the binaries + tool scripts as a
wheel, so there's nothing to install system-wide and no `SUMO_HOME` to set
(`_sumo_env.py` points it at the wheel). No SUMO GUI / XQuartz needed; the
pipeline is headless.

## Scope (first test)

- **Date:** 2025-07-28 (the demo matchday; kickoff 18:00).
- **Lines:** 1, 3, 5, X4 — 3 & 5 serve Jahnstadion, 1 is the flagship corridor,
  X4 the express. (No built-in line filter in gtfs2pt, so `subset_gtfs.py`
  pre-cuts the feed.)
- **Window:** 16:00–21:00. Widen `BEGIN`/`END` in `subset_gtfs.py` +
  `run_sim.py` (and the lines in `subset_gtfs.LINES`) to grow coverage.

## Outputs

All under `analysis/data/sumo/` — **gitignored + regenerable** (covered by the
root `analysis/data/**` rule). Served by the backend at `GET /sim/{date}` and
consumed by the frontend `BusLayer`.

`trajectories_<date>.json`:

```jsonc
{
  "date": "2025-07-28", "begin": 57600, "end": 75597,
  "buses": [
    { "id": "...", "line": "3", "points": [[t, lon, lat, angle], ...] }
  ]
}
```

`t` = seconds since midnight; coords rounded to 5 dp (~1 m).

## Next: reroute (scripted, not yet built)

Replace `run_sim.py`'s plain `sumo` run with a TraCI loop (`traci` is already a
dep): at kickoff, pick one bus near Jahnstadion and `changeTarget` / `setRoute`
it onto the stadium leg, then return it — tagging it so the FCD/exporter can
flag `diverted: true` for the frontend to highlight.
