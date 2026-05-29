#!/usr/bin/env python3
"""Convert a geo FCD output (sim.fcd.xml) into a compact JSON for the browser viewer.

Frames are downsampled to every STEP seconds. Each frame is a list of
[vehicle_index, lon, lat, angle]. Vehicle metadata (id, line) is emitted once.
"""
import json
import re
import sys
from xml.etree import ElementTree as ET

SRC = sys.argv[1] if len(sys.argv) > 1 else "sim.fcd.xml"
OUT = sys.argv[2] if len(sys.argv) > 2 else "viewer_data.json"
STEP = int(sys.argv[3]) if len(sys.argv) > 3 else 3  # seconds between frames
VEHICLES = sys.argv[4] if len(sys.argv) > 4 else "gtfs_pt_vehicles.add.xml"
DATE = sys.argv[5] if len(sys.argv) > 5 else ""  # label shown in the viewer

# The REAL RVV line (from GTFS routes.txt route_short_name) is stored in the
# `line=` attribute of the gtfs2pt vehicles file, keyed by vehicle id. Build
# {vehicle_id -> line}. The token in the id itself is only an internal index.
LINE_RE = re.compile(r"/([^/_]+)__")  # fallback only


def build_line_map(path: str) -> dict[str, str]:
    m: dict[str, str] = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "vehicle":
            vid, line = el.get("id"), el.get("line")
            if vid and line is not None:
                m[vid] = line.split("#")[0]  # strip route-variant suffix (e.g. 10#11 -> 10)
            el.clear()
    return m


LINE_MAP = build_line_map(VEHICLES)


def line_of(vid: str) -> str:
    if vid in LINE_MAP:
        return LINE_MAP[vid]
    m = LINE_RE.search(vid)  # fallback if id not found in vehicles file
    return m.group(1) if m else "?"


veh_index: dict[str, int] = {}
veh_meta: list[dict] = []
frames: list[dict] = []
begin = None

context = ET.iterparse(SRC, events=("end",))
for _, elem in context:
    if elem.tag != "timestep":
        continue
    t = float(elem.get("time"))
    if begin is None:
        begin = t
    if int(t - begin) % STEP == 0:
        positions = []
        for v in elem.findall("vehicle"):
            vid = v.get("id")
            if vid not in veh_index:
                veh_index[vid] = len(veh_meta)
                veh_meta.append({"id": vid, "line": line_of(vid)})
            positions.append([
                veh_index[vid],
                round(float(v.get("x")), 5),
                round(float(v.get("y")), 5),
                round(float(v.get("angle", 0)), 1),
            ])
        frames.append({"t": int(t), "p": positions})
    elem.clear()  # free memory

data = {
    "date": DATE,
    "begin": int(begin),
    "step": STEP,
    "vehicles": veh_meta,
    "frames": frames,
}
with open(OUT, "w") as f:
    json.dump(data, f, separators=(",", ":"))

print(f"vehicles={len(veh_meta)} frames={len(frames)} -> {OUT}")
