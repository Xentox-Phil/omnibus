"""Ingest RVV ITCS CSVs (UTF-16, German columns) -> tidy Parquet.

Usage:
    .venv/bin/python pipeline/ingest.py                 # all files
    .venv/bin/python pipeline/ingest.py --file NAME.csv # one file

Quirks handled (see CLAUDE.md):
  - UTF-16 encoding.
  - 25 columns; empty-header columns at idx 10/12/14/17/19 carry sub-values.
  - Numerics use '.' as a THOUSANDS separator ("-1.499" -> -1499).
  - Timestamps "%d.%m.%Y %H:%M:%S"; missing door timestamp => doors never opened.
"""

from __future__ import annotations

import argparse
import csv
import io
from io import BytesIO
from pathlib import Path

import polars as pl

RAW_DIR = Path("data/raw/rvv")
OUT_DIR = Path("data/parquet")

# Positional names for all 25 columns (incl. the empty-header sub-value cols).
COLS = [
    "ts_arrival_actual_door",   # 0  Ankunft Haltestelle (Tür)
    "ts_arrival_actual_halt",   # 1  Ankunft Haltestelle (Halt)
    "ts_arrival_planned",       # 2  Ankunft PLAN (Haltestelle)
    "ts_departure_actual_door", # 3  Abfahrt Haltestelle (Tür)
    "ts_departure_actual_halt", # 4  Abfahrt Haltestelle (Halt)
    "ts_departure_planned",     # 5  Abfahrt PLAN (Haltestelle)
    "productive_arr",           # 6  Ankunft produktiv  (Ja/Nein)
    "productive_dep",           # 7  Abfahrt produktiv  (Ja/Nein)
    "operating_day",            # 8  Betriebstag
    "trip_start_code",          # 9  Fahrtbeginn (Soll-Haltestelle) code
    "trip_start_name",          # 10 (sub) Fahrtbeginn long name
    "trip_end_code",            # 11 Fahrtende (Soll-Haltestelle) code
    "trip_end_name",            # 12 (sub) Fahrtende long name
    "stop_code",                # 13 Haltestelle code
    "stop_name",                # 14 (sub) Haltestelle long name
    "stop_point",               # 15 Haltepunkt (>=1 per stop)
    "line_id",                  # 16 Linie (internal id, e.g. 401)
    "line",                     # 17 (sub) public line label, e.g. "C2", "N5"
    "direction",                # 18 Richtung (1/2)
    "direction_label",          # 19 (sub) Richtung letter (A/B)
    "vehicle_block",            # 20 Umlauf (depot-to-depot duty)
    "delay_dep_avg_s",          # 21 Fahrplan-Abw. Abfahrt (Tür) AVG {s}
    "delay_arr_avg_s",          # 22 Fahrplan-Abw. Ankunft (Tür) AVG {s}
    "distance_cum_m",           # 23 CUMSUM(Distanz PLAN) {m}
    "runtime_cum_s",            # 24 CUMSUM(Fahrzeit IST) {s}
]

TS_COLS = [c for c in COLS if c.startswith("ts_")]
INT_COLS = ["delay_dep_avg_s", "delay_arr_avg_s", "distance_cum_m", "runtime_cum_s"]
TS_FMT = "%d.%m.%Y %H:%M:%S"

# Identity (non-metric) columns shared by both wide and melted exports.
IDENTITY = COLS[:21]
# Line-1 export is melted: one row per (event, metric). Map metric name -> wide column.
# Whitespace is collapsed before lookup (source has inconsistent spacing).
METRIC_MAP = {
    "Fahrplan-Abw. Abfahrt (Tür) AVG {s}": "delay_dep_avg_s",
    "Fahrplan-Abw. Ankunft (Tür) AVG {s}": "delay_arr_avg_s",
    "CUMSUM(Distanz PLAN) {m}": "distance_cum_m",
    "CUMSUM(Fahrzeit IST) {s}": "runtime_cum_s",
}

# German header label -> canonical identity column (for header-driven parsing).
GERMAN_BASE = {
    "Ankunft Haltestelle (Tür)": "ts_arrival_actual_door",
    "Ankunft Haltestelle (Halt)": "ts_arrival_actual_halt",
    "Ankunft PLAN (Haltestelle)": "ts_arrival_planned",
    "Abfahrt Haltestelle (Tür)": "ts_departure_actual_door",
    "Abfahrt Haltestelle (Halt)": "ts_departure_actual_halt",
    "Abfahrt PLAN (Haltestelle)": "ts_departure_planned",
    "Ankunft produktiv": "productive_arr",
    "Abfahrt produktiv": "productive_dep",
    "Betriebstag": "operating_day",
    "Fahrtbeginn (Soll-Haltestelle)": "trip_start_code",
    "Fahrtende (Soll-Haltestelle)": "trip_end_code",
    "Haltestelle": "stop_code",
    "Haltepunkt": "stop_point",
    "Linie": "line_id",
    "Richtung": "direction",
    "Umlauf": "vehicle_block",
}
# An empty header column directly follows these and carries their sub-value.
GERMAN_SUB = {
    "trip_start_code": "trip_start_name",
    "trip_end_code": "trip_end_name",
    "stop_code": "stop_name",
    "line_id": "line",
    "direction": "direction_label",
}


def resolve_melted_header(fields: list[str]) -> list[str]:
    """Map a melted file's raw header fields to canonical names.

    Melted exports vary in which identity columns are present (some drop
    Haltepunkt or Haltestelle). Empty header fields carry the preceding
    column's sub-value; the final two trailing empties are the metric
    name/value pair.
    """
    names: list[str] = []
    pending_sub: str | None = None
    metric_slots = ["_metric", "_value"]
    for raw in fields:
        label = raw.strip()
        if label in GERMAN_BASE:
            canon = GERMAN_BASE[label]
            names.append(canon)
            pending_sub = GERMAN_SUB.get(canon)
        elif label == "" and pending_sub:
            names.append(pending_sub)
            pending_sub = None
        elif label == "" and metric_slots:
            names.append(metric_slots.pop(0))
        else:
            names.append(label or f"_unused_{len(names)}")
    return names


def _to_int(col: str) -> pl.Expr:
    # '.' is a thousands separator: "-1.499" -> -1499. Empty -> null.
    return (
        pl.col(col)
        .str.replace_all(".", "", literal=True)
        .str.strip_chars()
        .replace("", None)
        .cast(pl.Int64, strict=False)
        .alias(col)
    )


def transform(df: pl.DataFrame) -> pl.DataFrame:
    df = df.with_columns(
        [pl.col(c).str.to_datetime(TS_FMT, strict=False).alias(c) for c in TS_COLS]
        + [pl.col(c).str.to_date("%d.%m.%Y", strict=False).alias(c) for c in ["operating_day"]]
        + [(pl.col(c) == "Ja").alias(c) for c in ["productive_arr", "productive_dep"]]
        + [_to_int(c) for c in INT_COLS]
    )
    # Derived fields (CLAUDE.md).
    df = df.with_columns(
        (pl.col("ts_arrival_actual_door") - pl.col("ts_arrival_planned"))
        .dt.total_seconds().alias("delay_arr_s"),
        (pl.col("ts_departure_actual_door") - pl.col("ts_departure_planned"))
        .dt.total_seconds().alias("delay_dep_s"),
        (pl.col("ts_departure_actual_door") - pl.col("ts_arrival_actual_door"))
        .dt.total_seconds().alias("dwell_s"),
        pl.col("ts_arrival_actual_door").is_not_null().alias("door_opened"),
    )
    return add_trip_id(df)


# A trip = one run of a single (line, direction, origin, destination) within a
# vehicle_block on an operating_day. See docs/DATA_DEFECTS.md §11.
TRIP_TUPLE = ["line", "direction", "trip_start_code", "trip_end_code"]


def add_trip_id(df: pl.DataFrame) -> pl.DataFrame:
    """Reconstruct a per-trip id and within-trip stop sequence.

    Ordering: ts_arrival_planned (the bus reaches its origin terminal first,
    so arrival is monotonic within a trip — departure is NOT, due to terminal
    layovers). Ties broken by distance DESC so a trip's final stop sorts before
    the next trip's origin (planned times are minute-coarse). A new trip begins
    only when the identity tuple changes within a (operating_day, vehicle_block).
    """
    block = ["operating_day", "vehicle_block"]
    df = df.with_columns(
        pl.coalesce("ts_arrival_planned", "ts_departure_planned").alias("_order_ts")
    ).sort([*block, "_order_ts", "distance_cum_m"], descending=[False, False, False, True])
    prev = pl.struct(TRIP_TUPLE).shift(1).over(block)
    is_new = (pl.struct(TRIP_TUPLE) != prev) | prev.is_null()
    df = df.with_columns(is_new.cum_sum().over(block).alias("_trip_seq"))
    df = df.with_columns(
        (
            pl.col("operating_day").cast(pl.Utf8)
            + "_" + pl.col("vehicle_block").fill_null("NA")
            + "_" + pl.col("_trip_seq").cast(pl.Utf8)
        ).alias("trip_id")
    )
    df = df.with_columns(
        pl.col("distance_cum_m").rank("ordinal").over("trip_id").alias("stop_seq")
    )
    return df.drop("_order_ts", "_trip_seq")


def read_raw(data: bytes | Path) -> pl.DataFrame:
    src = data if isinstance(data, (bytes, BytesIO)) else data
    return pl.read_csv(
        src,
        encoding="utf-16",
        has_header=True,
        new_columns=COLS,
        infer_schema_length=0,  # all strings; we cast explicitly
    )


def process_csv(path: Path) -> Path:
    df = transform(read_raw(path))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / (path.stem + ".parquet")
    df.write_parquet(out, compression="zstd")
    print(f"  {path.name}: {df.height:,} rows -> {out} ({out.stat().st_size/1e6:.1f} MB)")
    return out


def read_melted(buf: BytesIO) -> pl.DataFrame:
    """Pivot a melted (long) export back to the wide 25-column layout.

    The metric name/value are always the final two fields, but the identity
    columns in between vary by month, so we resolve column names from the
    header rather than by fixed position.
    """
    data = buf.getvalue()
    header = next(csv.reader(io.StringIO(data.decode("utf-16").splitlines()[0])))
    names = resolve_melted_header(header)
    raw = pl.read_csv(
        BytesIO(data),
        encoding="utf-16",
        has_header=False,
        skip_rows=1,
        schema={name: pl.String for name in names},
        truncate_ragged_lines=True,
    )
    index = [c for c in IDENTITY if c in raw.columns]
    raw = raw.with_columns(
        pl.col("_metric").str.replace_all(r"\s+", " ").str.strip_chars()
    )
    wide = raw.pivot(
        values="_value", index=index, on="_metric", aggregate_function="first"
    )
    wide = wide.rename({k: v for k, v in METRIC_MAP.items() if k in wide.columns})
    # Add any identity/metric columns this month lacked, then order to COLS.
    for col in COLS:
        if col not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.String).alias(col))
    return wide.select(COLS)


# stop_point is "<stop_code> (<position>)", e.g. "HBF (51)". The text before the
# trailing " (NN)" is exactly the stop_code (verified 100%, 0 mismatches).
_STOP_POINT_POS = r"\s*\(\d+\)\s*$"


def reconcile_stop_identity(df: pl.DataFrame) -> pl.DataFrame:
    """Back-fill null stop_code / stop_name (Apr-2025 Line-1 defect, DATA_DEFECTS §4).

    Apr 2025 lacked the Haltestelle column, so its rows carry a valid stop_point
    but null stop_code/stop_name. stop_point embeds the stop_code as its prefix,
    and stop_point → stop_name is 1:1, so we recover both from the stop_point
    using a lookup built from the months that do carry the full identity. Fully
    self-contained: no external file, reproducible from the melted set alone.
    """
    n_code0 = df.filter(pl.col("stop_code").is_null()).height
    # 1) stop_code from the stop_point prefix where missing.
    df = df.with_columns(
        stop_code=pl.when(
            pl.col("stop_code").is_null() & pl.col("stop_point").is_not_null()
        )
        .then(pl.col("stop_point").str.replace(_STOP_POINT_POS, ""))
        .otherwise(pl.col("stop_code"))
    )
    # 2) stop_name from a stop_code → stop_name lookup (rows that carry both).
    lut = (
        df.filter(pl.col("stop_code").is_not_null() & pl.col("stop_name").is_not_null())
        .select("stop_code", "stop_name")
        .unique(subset=["stop_code"])
    )
    df = (
        df.join(lut, on="stop_code", how="left", suffix="_lut")
        .with_columns(stop_name=pl.coalesce("stop_name", "stop_name_lut"))
        .drop("stop_name_lut")
    )
    n_recovered = n_code0 - df.filter(pl.col("stop_code").is_null()).height
    n_left = df.filter(pl.col("stop_name").is_null() & pl.col("stop_point").is_not_null()).height
    print(f"  [reconcile] recovered stop_code for {n_recovered:,} rows; "
          f"{n_left:,} rows with a stop_point still lack a stop_name")
    return df


def _build_melted(named_buffers: list[tuple[str, BytesIO]]) -> Path:
    """Pivot + concatenate melted monthly CSVs into one full-period parquet."""
    parts = []
    for name, buf in named_buffers:
        parts.append(read_melted(buf))
        print(f"  read {name}: {parts[-1].height:,} events")
    df = transform(reconcile_stop_identity(pl.concat(parts)))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "Daten_Linie_1_2024-09_2025-08.parquet"
    df.write_parquet(out, compression="zstd")
    print(f"  -> {out}: {df.height:,} rows ({out.stat().st_size/1e6:.1f} MB)")
    return out


def process_melted_dir(path: Path) -> Path:
    """Melted Line-1 export delivered as an extracted folder of monthly CSVs."""
    csvs = sorted(path.glob("*.csv"))
    if not csvs:
        raise SystemExit(f"no melted CSVs in {path}")
    return _build_melted([(p.name, BytesIO(p.read_bytes())) for p in csvs])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="single filename within data/raw/rvv")
    args = ap.parse_args()

    if args.file:
        files = [RAW_DIR / args.file]
    else:
        # Wide event CSVs + the extracted Line-1 folder (unzip the RVV zip first).
        files = (
            sorted(RAW_DIR.glob("*.csv"))
            + sorted(p for p in RAW_DIR.glob("Daten Linie*") if p.is_dir())
        )
    if not files:
        raise SystemExit(f"no input files in {RAW_DIR}")
    for f in files:
        print(f"{f.name} ...")
        if f.is_dir():
            process_melted_dir(f)
        else:
            process_csv(f)


if __name__ == "__main__":
    main()
