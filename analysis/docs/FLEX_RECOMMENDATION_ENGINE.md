# Flex recommendation engine

The flex engine turns directional stop pressure into dispatcher-style bus
reallocation recommendations and a compact GTFS scenario overlay for SUMO/UI
replay.

## Command

Run from `analysis/`:

```bash
uv run python pipeline/flex_recommend.py --scenario-id jahn_match_demo --force
```

Outputs:

```text
data/scenarios/<scenario_id>/
├── fleet_snapshot.json
├── pressure_input.json
├── recommendations.json
├── scenario_gtfs.zip
└── scenario_manifest.json
```

Serve generated scenarios to the UI:

```bash
uv run python pipeline/serve_flex_scenarios.py --port 8090
```

Endpoints:

```text
GET /api/scenarios
GET /api/scenarios/<scenario_id>/recommendations.json
GET /api/scenarios/<scenario_id>/gtfs.zip
```

## Pressure input contract

The engine accepts the dense stop/tick handoff from the pressure model:

```json
{
  "date": "2024-10-19",
  "resolution_min": 15,
  "n_ticks": 96,
  "tick_times": ["00:00", "00:15", "..."],
  "nodes": [
    {
      "stop_code": "JAHN",
      "lat": 48.99102,
      "lon": 12.11224,
      "pressure_s": [0, 0, "..."],
      "pressure_norm": [0, 0, "..."],
      "baseline_s": [7.8, 7.8, "..."],
      "event_s": [0, 0, "..."],
      "events": [
        {
          "event_id": "jahn_vs_fortuna_duesseldorf_2024-10-19",
          "event_label": "Jahn vs Fortuna Düsseldorf",
          "active_ticks": [82, 83, 84, 85, 86, 87, 88, 89, 90],
          "contribution_s": [0, 0, "..."]
        }
      ]
    }
  ]
}
```

For a `JAHN` event node, the engine derives:

- inbound pressure from `Hauptbahnhof` and `Dachauplatz` to `Jahnstadion Regensburg`
- outbound pressure from `Jahnstadion Regensburg` to `Hauptbahnhof`

The engine still accepts the older explicit stop-pair format for debugging:

```json
[
  {
    "time_bucket": "2025-05-11T17:45:00",
    "origin_stop_name": "Hauptbahnhof",
    "destination_stop_name": "Jahnstadion Regensburg",
    "pressure": 0.91,
    "confidence": 0.88,
    "reason": "Jahn kickoff in 45 minutes",
    "expected_duration_min": 50
  }
]
```

Then run:

```bash
uv run python pipeline/flex_recommend.py --pressure-json path/to/pressure.json --scenario-id my_scenario --force
```

`pressure` and `confidence` should be normalized to `0..1`.

For a ready-made smoke test before the model output is available:

```bash
uv run python pipeline/flex_recommend.py --pressure-json docs/example_pressure_jahn_dense.json --scenario-id example_pressure_jahn --force
```

Inspect:

```text
data/scenarios/example_pressure_jahn/recommendations.json
data/scenarios/example_pressure_jahn/scenario_gtfs.zip
```

## Recommendation logic

The engine:

1. Loads real RVV stop coordinates and representative line stop sequences from
   `data/parquet/features.parquet`.
2. Clusters compatible directional pressure predictions into temporary flex
   missions.
3. Builds mocked but explicit fleet candidates for data RVV did not provide
   (`bus_id`, capacity, flex capability, terminal status, route constraints).
4. Rejects any bus that is not flex-capable, is mid-route, belongs to a protected
   route, would violate minimum active service, or serves the active pressure
   itself.
5. Scores feasible donor/mission pairs:

```text
score =
  pressure relief
+ terminal availability timing
+ model confidence
+ capacity added
+ donor pullability
- donor route damage
```

Hard rule: a flex bus can only be pulled when its mocked status is `route_start`
or `route_end`. Mid-route buses appear in `rejected_donor_candidates` and are not
selected.

## GTFS output

`scenario_gtfs.zip` is a complete scenario feed. It copies the base GTFS files
from `data/raw/gtfs/`, then appends our scenario passenger-service rows. It
contains:

- `agency.txt`
- `stops.txt`
- `routes.txt`
- `trips.txt`
- `stop_times.txt`
- `calendar.txt`
- `calendar_dates.txt`

Each selected bus gets:

- a synthetic regular donor trip on its original public route, usually route
  `10`, with `block_id = bus_id`
- a passenger-serving relief trip on an existing public route, currently route
  `5` for the Jahnstadion demo, with the same `block_id`

The GTFS intentionally does **not** create fake `FLEX-*` routes. The route list
stays clean: the animator should see the flex bus running route `10`, then route
`5`.

The non-passenger repositioning move is represented in `scenario_manifest.json`,
not as a GTFS route. Use this sidecar to draw an optional dashed movement:

```json
{
  "vehicle_id": "FLEX_10_02",
  "segments": [
    {"type": "service", "route_id": "10"},
    {"type": "reposition", "from_stop": "Königswiesen", "to_stop": "Hauptbahnhof"},
    {"type": "service", "route_id": "5"}
  ]
}
```

Because the service trips share the same `block_id`, the animation layer can
show the same physical bus moving along Line 10, repositioning, then running the
route 5 relief trip.

The recommendation JSON remains the source for explanations, donor-route damage,
cancelled mocked next trip ids, and scoring details.
