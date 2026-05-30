"""Run the whole SUMO scenario pipeline end-to-end.

  uv run python pipeline/sumo/run_all.py [--force]

Chains the four steps in order. Each step is idempotent (skips if its output
exists); pass --force to rebuild everything from the OSM download down.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

STEPS = [
    "build_network.py",
    "subset_gtfs.py",
    "import_pt.py",
    "run_sim.py",
    "export_trajectories.py",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    for step in STEPS:
        cmd = [sys.executable, str(here / step)]
        if args.force:
            cmd.append("--force")
        print(f"\n=== {step} ===", flush=True)
        subprocess.run(cmd, check=True)
    print("\nscenario ready -> data/sumo/trajectories_2025-07-28.json")


if __name__ == "__main__":
    main()
