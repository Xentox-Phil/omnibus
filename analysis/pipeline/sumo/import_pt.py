"""Step 2b — map the subset GTFS onto the SUMO network (gtfs2pt.py).

  uv run python pipeline/sumo/import_pt.py [--force]

Produces the public-transport add-files the simulation loads:
  pt_stops.add.xml     bus stops snapped to lanes (+ the routes)
  pt_vehicles.add.xml  one vehicle per trip, with stop sequence + departure
  pt_vtypes.add.xml    bus vehicle type
Runs from data/sumo/ so gtfs2pt's intermediate fcd/ + gpsdat/ land there.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

import _sumo_env as env

DATE = "20250728"
BEGIN, END = 16 * 3600, 21 * 3600  # 16:00-21:00


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    env.setup()  # exports SUMO_HOME for the subprocess
    net = env.DATA_DIR / "regensburg.net.xml.gz"
    gtfs = env.DATA_DIR / f"gtfs_subset_{DATE}.zip"
    vehicles = env.DATA_DIR / "pt_vehicles.add.xml"
    stops = env.DATA_DIR / "pt_stops.add.xml"
    vtypes = env.DATA_DIR / "pt_vtypes.add.xml"

    if vehicles.exists() and not args.force:
        print(f"PT add-files exist: {vehicles} (use --force)")
        return
    for f in (net, gtfs):
        if not f.exists():
            sys.exit(f"missing input: {f} — run the earlier steps first")

    cmd = [
        sys.executable, env.tool("import/gtfs/gtfs2pt.py"),
        "-n", str(net),
        "--gtfs", str(gtfs),
        "--date", DATE,
        "--modes", "bus",
        "-b", str(BEGIN), "-e", str(END),
        "--vtype-output", str(vtypes),
        "--route-output", str(vehicles),
        "--additional-output", str(stops),
        "--repair",
        "-v",
    ]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(env.DATA_DIR))
    print(f"\nPT add-files written to {env.DATA_DIR}")


if __name__ == "__main__":
    main()
