"""Step 1 — build the SUMO road network for the Regensburg demo bbox.

  uv run python pipeline/sumo/build_network.py [--force]

Fetches an OSM extract (Overpass via osmGet.py) covering HBF + Jahnstadion, then
runs netconvert into a bus-drivable network. Idempotent: skips if outputs exist
unless --force. Outputs to analysis/data/sumo/ (gitignored, regenerable).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

import _sumo_env as env

# bbox: W,S,E,N — covers Hauptbahnhof (12.100,49.014) and Jahnstadion (12.112,48.991)
# with margin for the lines connecting them and the northern arenas.
BBOX = (12.04, 48.97, 12.20, 49.05)
PREFIX = "regensburg"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild even if outputs exist")
    args = ap.parse_args()

    home = env.setup()
    env.DATA_DIR.mkdir(parents=True, exist_ok=True)
    osm = env.DATA_DIR / f"{PREFIX}_bbox.osm.xml"
    net = env.DATA_DIR / f"{PREFIX}.net.xml.gz"

    if net.exists() and not args.force:
        print(f"network exists: {net} (use --force to rebuild)")
        return

    # 1. OSM extract via Overpass
    if not osm.exists() or args.force:
        run([
            sys.executable, env.tool("osmGet.py"),
            "--bbox", ",".join(map(str, BBOX)),
            "--prefix", PREFIX,
            "--output-dir", str(env.DATA_DIR),
        ])
    else:
        print(f"reusing OSM extract: {osm}")

    # 2. netconvert -> bus-drivable network
    typemaps = ",".join([
        str(home / "data" / "typemap" / "osmNetconvert.typ.xml"),
        str(home / "data" / "typemap" / "osmNetconvertBicycle.typ.xml"),
    ])
    run([
        env.binary("netconvert"),
        "--osm-files", str(osm),
        "--output-file", str(net),
        "--type-files", typemaps,
        "--geometry.remove",
        "--ramps.guess",
        "--junctions.join",
        "--tls.guess-signals",
        "--tls.discard-simple",
        "--tls.join",
        "--osm.elevation", "false",
        "--remove-edges.isolated",
        "--keep-edges.by-vclass", "passenger,bus,tram,rail_urban,coach",
        "--proj.utm",
        "--no-turnarounds.except-deadend",
    ])
    print(f"\nnetwork built: {net}")


if __name__ == "__main__":
    main()
