"""Pipeline conductor — runs every stage in dependency order with smart caching.

Each stage already self-caches (skip if its parquet exists). This conductor
sequences them, threads --force, resolves the one real dependency
(university_calendar needs holidays_bavaria first), soft-skips ingest when the
raw RVV bundle is absent (so a fresh clone can still build the external data),
and prints one summary table.

Dependency order:
    ingest                 raw RVV CSVs        -> <window>.parquet        (soft-skip if no raw)
    fetch_weather          Open-Meteo          -> weather + daylight
    fetch_holidays         Open-Holidays       -> holidays_bavaria
    fetch_university_cal.   OTH/UR + holidays   -> university_calendar     (needs holidays)
    ingest_external_csvs   manual events/strikes-> events + strikes        (soft-skip if no raw)
    fetch_gtfs             RVV stop master+GTFS -> stops_geo (stop_code→DHID→coords; needs ingest)
    assemble               all of the above    -> features.parquet         (needs everything)

Usage:
    uv run python pipeline/run.py                 # build everything missing
    uv run python pipeline/run.py --force         # rebuild everything
    uv run python pipeline/run.py --only weather,assemble
    uv run python pipeline/run.py --skip ingest
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
PARQUET = Path("data/parquet")
RAW = Path("data/raw")
RVV_RAW = RAW / "rvv"


def ingest_outputs() -> list[Path]:
    """Replicate ingest.py's output naming so we can cache-check without running it."""
    if not RVV_RAW.exists():
        return []
    outs = [PARQUET / (p.stem + ".parquet") for p in sorted(RVV_RAW.glob("*.csv"))]
    if any(p.is_dir() for p in RVV_RAW.glob("Daten Linie*")):
        outs.append(PARQUET / "Daten_Linie_1_2024-09_2025-08.parquet")
    return outs


def ingest_missing_raw() -> str | None:
    if not RVV_RAW.exists() or not ingest_outputs():
        return f"no raw RVV bundle in {RVV_RAW}/ — drop the CSVs there to build window parquets"
    return None


def external_missing_raw() -> str | None:
    needed = [RAW / "crawled" / "events_regensburg_2024_2025.csv", RAW / "crawled" / "strikes_rvv_2024_2025.csv"]
    if not all(p.exists() for p in needed):
        return f"manual CSVs absent in {RAW}/crawled/ (events/strikes)"
    return None


@dataclass
class Stage:
    name: str
    script: str
    outputs: Callable[[], list[Path]]
    supports_force: bool = True
    soft_skip: Callable[[], str | None] = lambda: None
    deps: list[str] = field(default_factory=list)


STAGES: list[Stage] = [
    Stage("ingest", "ingest.py", ingest_outputs,
          supports_force=False, soft_skip=ingest_missing_raw),
    Stage("fetch_weather", "fetch_weather.py",
          lambda: [PARQUET / "weather_regensburg.parquet", PARQUET / "daylight_regensburg.parquet"]),
    Stage("fetch_holidays", "fetch_holidays.py",
          lambda: [PARQUET / "holidays_bavaria.parquet"]),
    Stage("fetch_university_calendar", "fetch_university_calendar.py",
          lambda: [PARQUET / "university_calendar.parquet"], deps=["fetch_holidays"]),
    Stage("ingest_external_csvs", "ingest_external_csvs.py",
          lambda: [PARQUET / "events_regensburg.parquet", PARQUET / "strikes_rvv.parquet"],
          soft_skip=external_missing_raw),
    Stage("fetch_gtfs", "fetch_gtfs.py",
          lambda: [PARQUET / "stops_geo.parquet"],
          deps=["ingest"]),
    Stage("assemble", "assemble.py",
          lambda: [PARQUET / "features.parquet"],
          deps=["ingest", "fetch_weather", "fetch_holidays",
                "fetch_university_calendar", "ingest_external_csvs", "fetch_gtfs"]),
]


def run_stage(stage: Stage, force: bool) -> tuple[str, str]:
    """Returns (status, detail). status in CACHED/SKIP/RAN/FAIL/DEP-FAIL."""
    if (msg := stage.soft_skip()) is not None:
        return "SKIP", msg

    outs = stage.outputs()
    if outs and not force and all(p.exists() for p in outs):
        return "CACHED", f"{len(outs)} output(s) present"

    argv = [sys.executable, str(HERE / stage.script)]
    if force and stage.supports_force:
        argv.append("--force")

    print(f"\n── {stage.name} ──")
    rc = subprocess.run(argv).returncode
    if rc != 0:
        return "FAIL", f"exit {rc}"
    built = [p for p in stage.outputs() if p.exists()]
    return "RAN", f"{len(built)} output(s)"


def main() -> None:
    ap = argparse.ArgumentParser(description="Omnibus data pipeline conductor.")
    ap.add_argument("--force", action="store_true", help="rebuild every stage")
    ap.add_argument("--only", help="comma-separated stage names to run (others skipped)")
    ap.add_argument("--skip", help="comma-separated stage names to skip")
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    skip = {s.strip() for s in args.skip.split(",")} if args.skip else set()

    results: dict[str, str] = {}
    rows: list[tuple[str, str, str]] = []
    for stage in STAGES:
        if only is not None and stage.name not in only:
            continue
        if stage.name in skip:
            rows.append((stage.name, "SKIP", "excluded via --skip"))
            continue
        failed_dep = next((d for d in stage.deps if results.get(d) == "FAIL"), None)
        if failed_dep:
            rows.append((stage.name, "DEP-FAIL", f"dependency {failed_dep} failed"))
            results[stage.name] = "FAIL"
            continue
        status, detail = run_stage(stage, args.force)
        results[stage.name] = status
        rows.append((stage.name, status, detail))

    width = max(len(n) for n, _, _ in rows)
    print("\n" + "═" * (width + 30))
    print("  PIPELINE SUMMARY")
    print("═" * (width + 30))
    for name, status, detail in rows:
        print(f"  {name:<{width}}  {status:<9} {detail}")
    print("═" * (width + 30))

    if any(s in ("FAIL", "DEP-FAIL") for _, s, _ in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
