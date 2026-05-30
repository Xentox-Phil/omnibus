"""Step 4 — turn geo FCD into a compact trajectories JSON for the web app.

  uv run python pipeline/sumo/export_trajectories.py [--force]

Reads fcd.xml.gz (lon/lat per timestep) + pt_vehicles.add.xml (id -> line) and
writes trajectories_<date>.json:

  {
    "date": "2025-07-28", "begin": 57600, "end": 75600, "period": 3,
    "buses": [ {"id": "...", "line": "3", "points": [[t, lon, lat, angle], ...]} ]
  }

t = seconds since midnight, coords rounded to 5 dp (~1 m). Streamed with
iterparse so the large FCD never lives fully in memory.
"""

from __future__ import annotations

import argparse
import gzip
import json
import xml.etree.ElementTree as ET

import _sumo_env as env

DATE = "20250728"
ISO_DATE = "2025-07-28"  # filename uses the dashed form, matching demand_<date>.json


def vehicle_lines() -> dict[str, str]:
    """id -> GTFS line short name, from the gtfs2pt vehicle add-file."""
    path = env.DATA_DIR / "pt_vehicles.add.xml"
    lines: dict[str, str] = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "vehicle":
            # gtfs2pt suffixes distinct stop-sequences as "3#1"; keep the base line
            lines[el.get("id")] = el.get("line", "?").split("#")[0]
            el.clear()
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out = env.DATA_DIR / f"trajectories_{ISO_DATE}.json"
    if out.exists() and not args.force:
        print(f"trajectories exist: {out} (use --force)")
        return

    lines = vehicle_lines()
    fcd = env.DATA_DIR / "fcd.xml.gz"
    buses: dict[str, list] = {}
    t = 0
    t_min, t_max = None, None

    with gzip.open(fcd, "rb") as fh:
        for ev, el in ET.iterparse(fh, events=("start", "end")):
            if el.tag == "timestep":
                if ev == "start":
                    t = int(float(el.get("time")))
                    t_min = t if t_min is None else min(t_min, t)
                    t_max = t if t_max is None else max(t_max, t)
                else:
                    el.clear()  # drop processed timestep + its vehicle children
            elif el.tag == "vehicle" and ev == "end":
                vid = el.get("id")
                buses.setdefault(vid, []).append([
                    t,
                    round(float(el.get("x")), 5),
                    round(float(el.get("y")), 5),
                    round(float(el.get("angle", 0)), 1),
                ])

    payload = {
        "date": ISO_DATE,
        "begin": t_min,
        "end": t_max,
        "buses": [
            {"id": vid, "line": lines.get(vid, "?"), "points": pts}
            for vid, pts in buses.items()
        ],
    }
    out.write_text(json.dumps(payload, separators=(",", ":")))
    n_pts = sum(len(b["points"]) for b in payload["buses"])
    print(
        f"wrote {out}  ({out.stat().st_size // 1024} KB)\n"
        f"  buses={len(payload['buses'])}  points={n_pts}  "
        f"span={t_min}-{t_max}s"
    )


if __name__ == "__main__":
    main()
