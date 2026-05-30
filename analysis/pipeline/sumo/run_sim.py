"""Step 3 — run the SUMO simulation and emit geo FCD.

  uv run python pipeline/sumo/run_sim.py [--force]

Writes a sumocfg, runs sumo headless, and produces fcd.xml.gz with per-vehicle
lon/lat per sampled timestep (--fcd-output.geo). Sampled every FCD_PERIOD s to
keep the file small; the frontend interpolates between samples anyway.
"""

from __future__ import annotations

import argparse
import subprocess

import _sumo_env as env

BEGIN, END = 16 * 3600, 21 * 3600  # 16:00-21:00
FCD_PERIOD = 3  # seconds between FCD samples


SUMOCFG = """<configuration>
    <input>
        <net-file value="regensburg.net.xml.gz"/>
        <additional-files value="pt_vtypes.add.xml,pt_stops.add.xml,pt_vehicles.add.xml"/>
    </input>
    <time>
        <begin value="{begin}"/>
        <end value="{end}"/>
    </time>
    <processing>
        <ignore-route-errors value="true"/>
        <time-to-teleport value="300"/>
    </processing>
    <report>
        <no-step-log value="true"/>
        <duration-log.disable value="true"/>
    </report>
</configuration>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    env.setup()
    cfg = env.DATA_DIR / "sim.sumocfg"
    fcd = env.DATA_DIR / "fcd.xml.gz"
    if fcd.exists() and not args.force:
        print(f"FCD exists: {fcd} (use --force)")
        return

    cfg.write_text(SUMOCFG.format(begin=BEGIN, end=END))
    cmd = [
        env.binary("sumo"),
        "-c", str(cfg),
        "--fcd-output", str(fcd),
        "--fcd-output.geo", "true",
        "--device.fcd.period", str(FCD_PERIOD),
        "--fcd-output.attributes", "id,x,y,speed,angle",
    ]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(env.DATA_DIR))
    print(f"\nFCD written: {fcd}  ({fcd.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
