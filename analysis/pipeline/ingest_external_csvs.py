"""Ingest manually-curated external CSVs -> Parquet siblings.

Reads the per-row-sourced CSVs in data/raw/ produced by the research workflow
(see docs/EVENTS.md, docs/STRIKES.md) and writes typed parquets for polars joins.

Usage:
    uv run python pipeline/ingest_external_csvs.py
    uv run python pipeline/ingest_external_csvs.py --force
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

RAW = Path("data/raw")
OUT = Path("data/parquet")

EVENTS_CSV = RAW / "events_regensburg_2024_2025.csv"
STRIKES_CSV = RAW / "strikes_rvv_2024_2025.csv"
EVENTS_PARQUET = OUT / "events_regensburg.parquet"
STRIKES_PARQUET = OUT / "strikes_rvv.parquet"


def ingest_events(force: bool) -> None:
    if EVENTS_PARQUET.exists() and not force:
        print(f"{EVENTS_PARQUET} exists — skip.")
        return
    df = pl.read_csv(EVENTS_CSV).with_columns(
        pl.col("date").str.to_date("%Y-%m-%d"),
        # approx_attendance may contain "unknown"; coerce to nullable Int64.
        pl.col("approx_attendance").cast(pl.Int64, strict=False),
    ).sort(["date", "event_name"])
    df.write_parquet(EVENTS_PARQUET, compression="zstd")
    print(f"  {df.height:,} rows -> {EVENTS_PARQUET} ({EVENTS_PARQUET.stat().st_size / 1e3:.1f} kB)")


def ingest_strikes(force: bool) -> None:
    if STRIKES_PARQUET.exists() and not force:
        print(f"{STRIKES_PARQUET} exists — skip.")
        return
    df = pl.read_csv(STRIKES_CSV).with_columns(
        pl.col("date").str.to_date("%Y-%m-%d"),
    ).sort("date")
    df.write_parquet(STRIKES_PARQUET, compression="zstd")
    print(f"  {df.height:,} rows -> {STRIKES_PARQUET} ({STRIKES_PARQUET.stat().st_size / 1e3:.1f} kB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if not EVENTS_CSV.exists():
        raise SystemExit(f"missing {EVENTS_CSV}; see docs/EVENTS.md")
    if not STRIKES_CSV.exists():
        raise SystemExit(f"missing {STRIKES_CSV}; see docs/STRIKES.md")

    ingest_events(args.force)
    ingest_strikes(args.force)


if __name__ == "__main__":
    main()
