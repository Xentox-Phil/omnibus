"""Fold the three GTFS trips of a flex block into a single SUMO vehicle.

`gtfs2pt` emits one `<vehicle>` per GTFS trip. The flex engine writes each flex
duty as three trips that share a `block_id` (line-10 leg → OUT_OF_SERVICE
deadhead → relief leg), but `gtfs2pt` doesn't chain by block — it produces three
unrelated vehicles, and the inter-leg layover becomes a stretch of simulation
time with no vehicle for that block. The frontend has nothing to draw and the
flex bus disappears at the layover, then reappears as a fresh vehicle for the
relief leg. See `analysis/docs/FLEX_BLOCK_MERGE.md`.

This module post-processes `pt_vehicles.add.xml` after `gtfs2pt`:
  - group flex vehicles by FLEX_xx_yy block id (parsed from the vehicle id)
  - concatenate their routes into one continuous edge sequence, bridging any
    non-contiguous leg boundary via sumolib shortest-path (vClass=bus)
  - merge their stops; insert a `parking="true" until=<next-leg-depart>` stop
    on each inter-leg boundary edge so the bus parks during the layover
  - replace the per-leg vehicles + routes with one merged vehicle + route
    whose id is the block id (FLEX_10_02), keeping the regex hook the trajectory
    exporter uses to tag flex buses

The merged vehicle's `line` is set to `"FLEX"`; per-leg line identity (10/OUT/5)
is no longer carried at the SUMO level — the scenario manifest mirrors the
segments for any UI that needs them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

# Vehicle id prefix that identifies a flex-block leg, e.g.
# "FLEX_10_02_REGULAR_10_BEFORE_PULL.0" → block "FLEX_10_02".
FLEX_VEHICLE_RE = re.compile(r"^(FLEX_\d+_\d+)_")


def _bridge(net, src: str, dst: str) -> list[str]:
    """Edges that connect `src` to `dst` (excluding both endpoints).

    Returns [] if src == dst, or if no bus-class path exists (a warning prints
    and we let SUMO's --ignore-route-errors handle the resulting disconnect).
    """
    if src == dst:
        return []
    src_e, dst_e = net.getEdge(src), net.getEdge(dst)
    path, _ = net.getShortestPath(src_e, dst_e, vClass="bus")
    if not path:
        print(f"    WARN: no bus-routable bridge {src} -> {dst}")
        return []
    # path[0] == src_e, path[-1] == dst_e — drop both, they're already adjacent
    # to the previous/next leg's edge lists.
    return [e.getID() for e in path[1:-1]]


def _parking_stop(net, edge_id: str, until: int) -> ET.Element:
    """A `<stop parking="true" until=...>` near the end of the given edge.

    Used as the inter-leg layover: the bus arrives at the boundary edge after
    leg N, parks (no traffic interaction), and leaves no earlier than the next
    leg's GTFS departure time.
    """
    lane = net.getEdge(edge_id).getLane(0).getID()
    length = net.getEdge(edge_id).getLength()
    # endPos a hair shy of the edge end; startPos a 5 m parking slot.
    end_pos = max(1.0, length - 1.0)
    start_pos = max(0.0, end_pos - 5.0)
    return ET.Element("stop", {
        "lane": lane,
        "startPos": f"{start_pos:.2f}",
        "endPos": f"{end_pos:.2f}",
        "until": str(until),
        "parking": "true",
    })


def merge_flex_blocks(vehicles_path: Path, net_path: Path) -> int:
    """Rewrite `vehicles_path` in place; return the number of blocks merged."""
    import sumolib  # provided once env.setup() has put SUMO_HOME/tools on sys.path

    tree = ET.parse(vehicles_path)
    root = tree.getroot()

    routes = {r.get("id"): r for r in root.findall("route")}
    by_block: dict[str, list[ET.Element]] = defaultdict(list)
    for v in root.findall("vehicle"):
        m = FLEX_VEHICLE_RE.match(v.get("id", ""))
        if m:
            by_block[m.group(1)].append(v)

    if not by_block:
        return 0

    net = sumolib.net.readNet(str(net_path))

    for block_id, vehicles in by_block.items():
        vehicles.sort(key=lambda v: int(v.get("depart")))
        legs = []
        for v in vehicles:
            route = routes.get(v.get("route"))
            if route is None:
                print(f"  WARN: vehicle {v.get('id')} references missing route — skipping block {block_id}")
                legs = []
                break
            # gtfs2pt nests <stop> elements inside the standalone <route>, not the
            # <vehicle> that references it — so pull them off the route.
            legs.append({
                "vehicle": v,
                "route": route,
                "edges": route.get("edges", "").split(),
                "stops": list(route.findall("stop")),
                "depart": int(v.get("depart")),
            })
        if not legs:
            continue

        merged_edges: list[str] = list(legs[0]["edges"])
        merged_stops: list[ET.Element] = list(legs[0]["stops"])

        for i in range(1, len(legs)):
            prev_last, next_first = merged_edges[-1], legs[i]["edges"][0]
            bridge = _bridge(net, prev_last, next_first)
            # Inter-leg parking dwell sits on the BOUNDARY edge the bus parks on,
            # which is the prev leg's last edge (= where it stops driving).
            merged_stops.append(_parking_stop(net, prev_last, legs[i]["depart"]))
            if prev_last == next_first:
                merged_edges += legs[i]["edges"][1:]  # dedup shared boundary edge
            else:
                merged_edges += bridge + legs[i]["edges"]
            merged_stops += legs[i]["stops"]

        first = legs[0]["vehicle"]
        merged_route = ET.Element("route", {
            "id": f"{block_id}_route",
            "edges": " ".join(merged_edges),
        })
        merged_vehicle = ET.Element("vehicle", {
            "id": block_id,
            "route": f"{block_id}_route",
            "type": first.get("type", "bus"),
            "depart": str(legs[0]["depart"]),
            "line": "FLEX",
        })
        for stop in merged_stops:
            merged_vehicle.append(stop)

        for v in vehicles:
            root.remove(routes[v.get("route")])
            root.remove(v)
        root.append(merged_route)
        root.append(merged_vehicle)

    ET.indent(tree, space="    ")
    tree.write(vehicles_path, encoding="utf-8", xml_declaration=True)
    return len(by_block)
