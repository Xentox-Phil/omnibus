# Closures & Events — Data Format

How Omnibus represents anything that blocks a bus or changes its schedule — both **curated** scenarios (Bürgerfest, marathon, flood, Christkindlmarkt) and **operator-drawn** ad-hoc blockages (street closed for a burst water main, construction, etc.).

> Tied to `PLAN.md`: this is the input contract for step 2 *("Click road segments to mark them blocked — or pick a preset")* and the cost function defined there. The optimizer consumes a Scenario; this doc defines what a Scenario is.

## TL;DR

- One primitive: a **Closure**, encoded as a GeoJSON `Feature`.
- Two input modes for the operator: **click a single road** → LineString from the OSM way, or **lasso an area** → Polygon, intersected with OSM ways to produce the closed network.
- One library file: `events.geojson` — curated presets (Bürgerfest, marathon, flood, …).
- One runtime object: `Scenario` — what the operator is currently working on. References preset Closures + inline ad-hoc Closures. Disposable; optionally savable.
- Same data model for both flows. The collision engine does not know or care which mode produced a Closure.

## The Closure primitive

A Closure is a GeoJSON `Feature` with a constrained `properties` schema:

```json
{
  "type": "Feature",
  "id": "buergerfest-2025",
  "geometry": { "type": "Polygon", "coordinates": [[[12.094,49.018], ...]] },
  "properties": {
    "name": "Bürgerfest 2025",
    "category": "festival",
    "starts_at": "2025-06-20T15:00:00+02:00",
    "ends_at":   "2025-06-22T23:59:00+02:00",
    "affects":   ["road_closure", "demand_spike"],
    "severity":  "hard",
    "footprint_source": "manual_polygon",
    "osm_way_ids": [123, 456, 789],
    "source_url": "https://www.regensburg.de/buergerfest",
    "notes": "Altstadt — Domplatz, Haidplatz, Bismarckplatz"
  }
}
```

### Property reference

| Field               | Type                       | Required | Notes                                                                                  |
| ------------------- | -------------------------- | -------- | -------------------------------------------------------------------------------------- |
| `name`              | string                     | yes      | Human label. Shown in the UI.                                                          |
| `category`          | enum (see below)           | yes      | High-level kind. Drives icon + filter chips.                                           |
| `starts_at`         | ISO 8601 datetime          | yes      | Inclusive. Timezone-aware (Europe/Berlin).                                             |
| `ends_at`           | ISO 8601 datetime          | yes      | Exclusive in scoring; inclusive for display.                                           |
| `affects`           | array<enum>                | yes      | What operational effects this Closure has. See "affects vocabulary".                   |
| `severity`          | `"hard" \| "soft" \| "advisory"` | yes | hard = bus physically can't pass; soft = slow but possible; advisory = info only.    |
| `footprint_source`  | enum (see below)           | yes      | How the geometry was produced. Lets us re-resolve if upstream data changes.            |
| `osm_way_ids`       | array<int>                 | optional | Filled when the geometry was derived from OSM ways. Stable cross-reference.            |
| `source_url`        | string                     | optional | Provenance for curated entries.                                                        |
| `notes`             | string                     | optional | Free-text.                                                                             |

### Enums

**`category`**: `festival`, `roadwork`, `flood`, `parade`, `marathon`, `match` (Jahn / Eisbären), `protest`, `weather`, `operational` (FP-Wechsel, EMIL-13:00 cutoff, X1 day), `operator_adhoc`, `other`.

**`affects`** vocabulary (a Closure can carry multiple):

- `road_closure` — bus cannot traverse the geometry. Drives reroute search.
- `lane_restriction` — bus runs through but slower. Drives travel-time penalty, not reroute.
- `stop_unreachable` — a specific bus stop inside the geometry cannot be served.
- `demand_spike` — extra riders expected near the geometry (festival, match). Demand-side modifier.
- `demand_drop` — fewer riders (V-Frei, snow day).
- `schedule_override` — service runs on a different pattern (Samstagsfahrplan on weekday Heiligabend).
- `service_capacity_uplift` — extra runs added (X1 Berufsschulen day).
- `service_capacity_cut` — service reduced (EMIL/Altstadtbus 13:00 cutoff).

**`footprint_source`**: `manual_polygon`, `gpx`, `osm_overpass`, `nominatim`, `stop_buffer`, `operator_click`, `operator_polygon_draw`, `none` (= `geometry: null`, operational-only entry).

### Geometry types

| Geometry type           | Use case                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| `LineString`            | Single road segment (operator click on one OSM way), parade route, marathon course.         |
| `MultiLineString`       | Operator click on multiple ways, or lasso-resolved set of OSM ways.                         |
| `Polygon`               | Festival zone, flood area, lasso selection before OSM intersection.                         |
| `MultiPolygon`          | Disjoint zones (e.g. multiple flood patches).                                               |
| `Point`                 | Stadium, single intersection. Buffered server-side for collision tests.                     |
| `null`                  | Operational-only entry with no spatial footprint (X1 day, FP-Wechsel, Samstagsfahrplan).    |

## The two operator input modes

### Mode 1 — click a single way

1. Operator clicks on a rendered road.
2. Frontend hit-tests against an OSM way layer → captures `way_id` and the way's full LineString geometry.
3. Wraps it as a Closure with:
   - `geometry`: the way's LineString (or MultiLineString if a chain of adjacent ways was selected)
   - `properties.footprint_source`: `"operator_click"`
   - `properties.osm_way_ids`: `[way_id, ...]`
   - `properties.category`: defaults to `"operator_adhoc"`; operator can change to `"roadwork"`.

Click-to-extend behavior: click an adjacent way → append its way_id and extend the MultiLineString.

### Mode 2 — lasso / box-select an area

1. Operator drags a polygon (or a box) on the map.
2. Frontend or backend queries the local OSM way index for all ways that the polygon **intersects**. Filter to drivable ways only (`highway in {primary, secondary, tertiary, residential, …}`; exclude footways, cycleways, tracks).
3. Builds a Closure with:
   - `geometry`: `MultiLineString` of the intersected ways' geometries (so the renderer + the collision engine both work on roadway lines, not the lasso polygon).
   - `properties.footprint_source`: `"operator_polygon_draw"`
   - `properties.osm_way_ids`: the resolved list.
   - Also keep the original drawn polygon under `properties.raw_polygon` (GeoJSON) so the operator can re-edit the lasso without losing the source shape.

### Why we resolve lasso → ways

Without the OSM intersection, the reroute engine would have to test "does my candidate path pass through this polygon" using polygon ops on every edge — slow and noisy at intersection vertices. With the way-id resolution, collision becomes a set-membership check: `route uses way_id ∈ blocked_ways?`. Routing engines (OSRM, Valhalla, OpenTripPlanner) all accept way-id exclude lists natively.

## File layout

```
analysis/data/
  events/
    events.geojson                  # curated library (committed)
    scenarios/                      # saved demo scenarios — committed only after locked in for the pitch
  raw/
    crawled/
      events_regensburg_2024_2025.csv       # existing — date rows
      betriebskalender_events.csv           # existing — date rows
    osm/regensburg.osm.pbf                  # OSM extract for way lookup (gitignored)
  parquet/
    events_regensburg.parquet               # existing — day-rows derived from geojson
    closures_resolved.parquet               # optional: pre-resolved (closure × line × day)
```

### What's committed

- `events.geojson` — the curated library. **Source of truth** for presets.
- `scenarios/*.json` — only the canonical demo scenarios used in the pitch.
- Existing CSVs (`events_regensburg_2024_2025.csv`, `betriebskalender_events.csv`) — kept as-is; will be folded into `events.geojson` by a one-time migration.

### What's gitignored

- OSM PBF extracts (large, regenerable).
- Transient runtime scenarios (operator's current working state, never written to disk unless explicitly saved).

### What's derived (regenerable)

- `events_regensburg.parquet` — day-rows view of `events.geojson` (one row per event-day, for joining against telemetry).
- `closures_resolved.parquet` — pre-computed `(closure_id, route_id, stop_id, service_day)` tuples for fast scoring.

## The Scenario object

Runtime state for one in-progress operator session:

```json
{
  "scenario_id": "demo-buergerfest",
  "name": "Bürgerfest weekend — Sat afternoon",
  "window": {
    "starts_at": "2025-06-21T14:00:00+02:00",
    "ends_at":   "2025-06-21T20:00:00+02:00"
  },
  "closures": [
    { "ref": "buergerfest-2025" },
    {
      "inline": {
        "type": "Feature",
        "geometry": { "type": "MultiLineString", "coordinates": [...] },
        "properties": {
          "name": "Maximilianstraße — Burst pipe",
          "category": "operator_adhoc",
          "starts_at": "2025-06-21T14:30:00+02:00",
          "ends_at":   "2025-06-21T19:00:00+02:00",
          "affects": ["road_closure"],
          "severity": "hard",
          "footprint_source": "operator_click",
          "osm_way_ids": [12345678, 12345679]
        }
      }
    }
  ]
}
```

`closures[*]` is heterogeneous: either a `{ref}` pointer into the library, or an `{inline}` Feature. Both resolve to the same Closure primitive at collision time.

Scenarios are **disposable** by default. They become committable only when:
- A team member wants to share the demo state by URL.
- A canonical demo scenario gets locked in for the pitch — at which point it's checked into `scenarios/`.

## Collision detection — input/output contract

Detail belongs in a separate scoring doc, but for the storage format the contract is:

**Inputs:** a Scenario.
**Outputs:** a list of `Affected` records:

```json
{
  "closure_id":      "buergerfest-2025",
  "route_id":        "1",
  "direction_id":    0,
  "service_day":     "2025-06-21",
  "blocked_segments": [{ "shape_pt_seq": 87, "until_seq": 142 }],
  "blocked_stops":    ["de:09362:1234", "de:09362:1235"],
  "affected_trips":   ["tripA", "tripB", ...]
}
```

This feeds the optimizer's `dropped_stops` and `t_new(stop) − t_planned(stop)` terms from PLAN.md.

## Time-window mechanics

- Each Closure carries its own `starts_at` / `ends_at`. The Scenario's `window` filters which closures are active during scoring.
- A Closure is **active during a Scenario window** iff `closure.starts_at < window.ends_at AND closure.ends_at > window.starts_at`.
- Operator can override a Closure's time inline by editing it inside the Scenario without mutating the library entry.
- Day-of-week / service-id mapping uses GTFS `calendar.txt` + `calendar_dates.txt` — out of scope for this doc.

## Migration path from current state

`events_regensburg.parquet` and `betriebskalender_events.csv` are day-rows with no geometry. **Only entries with authoritative, year-stable geometry get migrated into `events.geojson`.** Anything whose perimeter shifts year-by-year (Bürgerfest, Christkindlmarkt, Schlossfestspiele, floods) stays as date-row context in the existing parquet — those become library Closures only after an operator draws them and saves a Scenario.

### Goes into `events.geojson`

| Source                          | Closure                          | Geometry                                | `affects`                                  |
| ------------------------------- | -------------------------------- | --------------------------------------- | ------------------------------------------ |
| `events_regensburg.parquet`     | Regensburg Marathon (per year)   | LineString from official GPX            | `road_closure`, `demand_spike`             |
| `events_regensburg.parquet`     | Jahn home games (per match)      | Point (Continental Arena) + buffer      | `demand_spike`                             |
| `events_regensburg.parquet`     | Eisbären home games (per match)  | Point (Donau-Arena) + buffer            | `demand_spike`                             |
| `events_regensburg.parquet`     | Dult Mai / Herbst (per year)     | Polygon (Dultplatz — fixed location)    | `demand_spike`                             |
| `betriebskalender_events.csv`   | X1 Berufsschulen day (per year)  | `null`                                  | `service_capacity_uplift`                  |
| `betriebskalender_events.csv`   | FP-Wechsel (per year, when known)| `null`                                  | `schedule_override`                        |
| `betriebskalender_events.csv`   | Samstagsfahrplan Heiligabend     | `null`                                  | `schedule_override`                        |
| `betriebskalender_events.csv`   | Samstagsfahrplan Silvester       | `null`                                  | `schedule_override`                        |
| `betriebskalender_events.csv`   | EMIL/Altstadtbus 13:00 cutoff    | `null`                                  | `service_capacity_cut`                     |
| `betriebskalender_events.csv`   | V-Frei (per occurrence)          | `null`                                  | `demand_drop`                              |
| `betriebskalender_events.csv`   | Eislauf Linie D season           | `null`                                  | `service_capacity_uplift`                  |

### Stays as date-row context (not migrated)

- **Bürgerfest, Christkindlmarkt, Schlossfestspiele** — perimeter varies year-by-year and isn't published as GeoJSON.
- **Floods** — geometry only exists after the fact, never as a planned input.
- **Public holidays** — sourced cleaner from `holidays_bavaria.parquet`; don't duplicate.
- **Sommerzeit transitions** — already covered by `daylight_regensburg.parquet`; operational impact marginal.
- **Modul** tentative dates — too vague to act on.

These remain as filter-able context for telemetry analysis; they become Closures only when an operator draws them at demo time and saves the Scenario.

### Re-emit derived parquet

`events_regensburg.parquet` continues to be the day-rows view used by notebooks; it picks up rows from `events.geojson` plus the unmigrated curated CSVs.

## What's out of scope for the hackathon

- Parsing PDFs / Verkehrsbehörde notices automatically. Manual polygon entry only.
- Live OSM Overpass calls during operator interaction — the operator only acts on a pre-downloaded Regensburg OSM extract.
- Live traffic feeds (Google, TomTom).
- Multi-user concurrent scenario editing.
- Auth / per-operator audit trail.

## Open decisions

- **Backend storage of runtime Scenarios.** Local state only (frontend-only) is simplest and matches a single-demo workflow. A thin Redis/SQLite for shareable URLs is the v2 hook.
- **OSM way snapping precision.** Clicking pixel-accurate on a way at high zoom is fine; at low zoom we need a snap tolerance (suggest 8–12px in screen space).
- **How `severity: "soft"` interacts with the routing engine.** OSRM doesn't take weight modifiers per way easily; for hackathon, treat `soft` as `hard` and revisit only if time allows.
