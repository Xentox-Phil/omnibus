#!/usr/bin/env python3
"""Generate a SAMPLE demand.json in the team's tick-based schema.

Schema (this is what a colleague will send; the viewer reads `pressure_norm`):

{
  "date": "2024-10-19",
  "resolution_min": 15,            # minutes per tick
  "n_ticks": 96,                   # 24h / 15min
  "tick_times": ["00:00", ..., "23:45"],
  "nodes": [
    { "stop_code": "JAHN", "lat": 48.99102, "lon": 12.11224,
      "pressure_s":    [...],      # absolute seconds (dwell pressure)
      "pressure_norm": [...],      # 0..1, normalized GLOBALLY  <-- drives color
      "baseline_s":    [...],      # event-free baseline
      "event_s":       [...],      # event contribution
      "events": [...] },           # per-event detail (empty if none)
    ...
  ]
}

Here we fill `pressure_norm` (and the other arrays) with randomized values and
take lat/lon from the GTFS bus stops. Replace this file with the real one later.
"""
import csv
import io
import json
import math
import random
import zipfile

DATE = "2025-08-01"
RES_MIN = 15
N_TICKS = 24 * 60 // RES_MIN          # 96
SEED = 42
random.seed(SEED)

tick_times = [f"{(i*RES_MIN)//60:02d}:{(i*RES_MIN)%60:02d}" for i in range(N_TICKS)]

# --- bus stops from GTFS (dedupe by name) ---
with zipfile.ZipFile("gtfs.zip") as z:
    text = z.read("stops.txt").decode("utf-8-sig")
seen, stops = set(), []
for r in csv.DictReader(io.StringIO(text)):
    if not (r.get("stop_lat") and r.get("stop_lon")):
        continue
    name = r.get("stop_name") or r["stop_id"]
    if name in seen:
        continue
    seen.add(name)
    stops.append((name, float(r["stop_lat"]), float(r["stop_lon"])))

CX, CY = 12.095, 49.013   # rough city centre for a mild "busier centre" bias


def bump(tick, peak_tick, width, height):
    return height * math.exp(-((tick - peak_tick) ** 2) / (2 * width ** 2))


# --- per-stop raw pressure curves (seconds), then global-normalize to 0..1 ---
raw = []
for name, lat, lon in stops:
    d = math.hypot(lon - CX, lat - CY)
    centre = max(0.2, 1.0 - d * 12)
    # rush peaks: morning (~tick 30), and an evening peak placed INSIDE the
    # simulated 20:00-21:00 window (ticks 80-84) so the heatmap is lively then.
    m_h = random.uniform(0.3, 1.0) * centre
    e_h = random.uniform(0.4, 1.0) * centre
    m_t = random.uniform(28, 36)
    e_t = random.uniform(79, 85)          # 19:45-21:15 -> covers the sim window
    base = random.uniform(5, 10)
    curve = []
    for i in range(N_TICKS):
        secs = base + 1500 * (bump(i, m_t, 5, m_h) + bump(i, e_t, 4, e_h))
        secs *= random.uniform(0.9, 1.1)   # noise
        curve.append(secs)
    raw.append(curve)

global_max = max(max(c) for c in raw) or 1.0

nodes = []
for (name, lat, lon), curve in zip(stops, raw):
    pressure_s = [round(x, 1) for x in curve]
    pressure_norm = [round(x / global_max, 4) for x in curve]
    baseline_s = [round(min(10.0, x), 1) for x in curve]    # flat-ish event-free part
    event_s = [round(max(0.0, x - b), 1) for x, b in zip(curve, baseline_s)]
    nodes.append({
        "stop_code": name,
        "lat": round(lat, 5), "lon": round(lon, 5),
        "pressure_s": pressure_s,
        "pressure_norm": pressure_norm,
        "baseline_s": baseline_s,
        "event_s": event_s,
        "events": [],          # no synthetic events in the sample
    })

data = {
    "date": DATE,
    "resolution_min": RES_MIN,
    "n_ticks": N_TICKS,
    "tick_times": tick_times,
    "nodes": nodes,
}
with open("demand.json", "w") as f:
    json.dump(data, f, separators=(",", ":"))

print(f"{len(nodes)} stops, {N_TICKS} ticks @ {RES_MIN}min -> demand.json")
