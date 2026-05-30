"""Train the general-demand prediction model -> data/models/demand_lgbm.txt.

This is the *general, non-directional* demand engine (PLAN.md): it predicts the
aggregate boarding-dwell at a stop in a given hour under given conditions.
Querying it on a fine time grid gives a smooth demand surface — it fills the
headway gaps a raw histogram leaves empty, because it pools strength across
days, nearby stops, and similar conditions. Directional event flows (Hbf<->Jahn)
are a *separate declared layer*, not learned here (dwell has no direction).

Why a model and not finer bucketing: the dwell signal only exists when a bus is
at the stop, so raw resolution is capped by headway (~84% of stop x 5-min cells
are empty in a 2-week sample). The model interpolates that; a histogram can't.

Target = AGGREGATE, not per-event. We predict log1p(total boarding-dwell per
(stop, hour, day)). Per-event dwell turned out to be ~84% pure stop identity:
demand doesn't lengthen each bus's dwell much, it adds buses and total boarding
activity, so the per-event target threw away the volume signal that actually
moves with time/weather/events. Summed dwell keeps it — and is the quantity the
surface and flex-router want anyway. (It conflates demand with scheduled supply,
since more buses => more total dwell; an accepted proxy, see PLAN.md.)

Features (all deterministic at inference — no weather/forecast input needed):
          stop (categorical) + lat/lon, cyclical hour + hour/dow categoricals,
          daylight, holiday/school flags, university in-session flags. Weather
          and event signals were dropped (see NUMERIC comment).

Training data: the 5 full-network ITCS capture windows. The Line-1 full-year
table is excluded — it overlaps the ITCS windows (double-counting Line 1) and
would swamp the loss with a single corridor. The special windows
(Christkindlmarkt, Hochwasser, UniLinien) are KEPT on purpose: they are the
condition variety (festival lift, flood, term-time) the model learns from.

Validation: hold out the Oct-2024 normal window and report MAE/RMSE in seconds,
against a (stop x hour x daytype) mean-lookup baseline — the model has to beat
that table to justify itself.

Cleaning matches notebook 07 / build_demand: drop terminus stops, dwell in
(0, 120] s, |arrival delay| < 2 h.

Idempotent: skips if the model artifact exists (use --force to retrain).
Requires libomp on macOS (`brew install libomp`).

Usage:
    uv run python pipeline/train_demand_model.py
    uv run python pipeline/train_demand_model.py --force
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

PARQUET = Path("data/parquet")
FEATURES = PARQUET / "features.parquet"
MODEL_DIR = Path("data/models")
MODEL_OUT = MODEL_DIR / "demand_lgbm.txt"
ENC_OUT = MODEL_DIR / "demand_encoders.json"

TRAIN_WINDOWS = [
    "08.10.2023_21.10.2023_ITCS",
    "06.10.2024_19.10.2024_ITCS",          # <- held out for validation
    "15.12.2024_25.12.2024_ITCS_Christkindlmarkt2024",
    "23.04.2025_09.05.2025_ITCS_nur_UniLinien",
    "26.05.2024_07.06.2024_ITCS_Hochwasser",
]
VAL_WINDOW = "06.10.2024_19.10.2024_ITCS"

DWELL_CAP_S, DELAY_CAP_S = 120, 7200

# Feature set is deliberately *deterministic at inference*: every feature is a
# function of (stop, datetime) or a calendar lookup — no weather/forecast input
# needed to query the model. Weather was dropped (whole block ~1% gain; snowfall
# 0.00%, transit is weather-inelastic) so predict_demand stays a pure function of
# date+stop. daylight_hours stays — it's astronomical (free from the date) and
# carries the season/winter signal weather would have. Event features dropped:
# events are added on top by the kernel (apply_events), not learned here.
NUMERIC = [
    "hour_sin", "hour_cos", "daylight_hours",
    "is_public_holiday", "is_school_holiday", "oth_in_session", "ur_in_session",
    "stop_lat", "stop_lon",
]
CATEGORICAL = ["stop_idx", "dow", "hour"]
FEATURES_ALL = NUMERIC + CATEGORICAL

NUMERIC_FILL = ["daylight_hours"]  # never null in practice; median-fill for safety

# day/hour-level context carried through aggregation (constant within a cell)
CTX_FIRST = [
    "daylight_hours", "is_public_holiday", "is_school_holiday",
    "oth_in_session", "ur_in_session", "stop_lat", "stop_lon", "source_window",
]


def load_clean() -> pl.DataFrame:
    lf = pl.scan_parquet(FEATURES).filter(
        pl.col("source_window").is_in(TRAIN_WINDOWS)
        & (pl.col("dwell_s") > 0)
        & (pl.col("dwell_s") <= DWELL_CAP_S)
        & (pl.col("delay_arr_s").abs() < DELAY_CAP_S)
        & pl.col("stop_lat").is_not_null()
    )
    # `is_terminus` is pre-computed in assemble.py on the full cleansed trip (before the
    # dwell/door filters above) — marks true endpoints, not the surviving first/last row.
    return lf.filter(~pl.col("is_terminus")).collect()


def aggregate(df: pl.DataFrame) -> pl.DataFrame:
    """Collapse stop-events to (stop, day, hour) cells; sum dwell = demand volume."""
    ts = pl.coalesce("ts_arrival_actual_door", "ts_departure_actual_door", "ts_arrival_planned")
    cells = (
        df.with_columns(ts.dt.hour().alias("hour"))
          .group_by("stop_code", "operating_day", "hour")
          .agg(pl.col("dwell_s").sum().alias("dwell_sum"),
               *[pl.col(c).first() for c in CTX_FIRST])
    )
    return cells.with_columns(
        pl.col("operating_day").dt.weekday().alias("dow"),          # 1=Mon .. 7=Sun
        (pl.col("operating_day").dt.weekday() >= 6).cast(pl.Int8).alias("is_weekend"),
        (2 * np.pi * pl.col("hour") / 24).sin().alias("hour_sin"),
        (2 * np.pi * pl.col("hour") / 24).cos().alias("hour_cos"),
        pl.col("dwell_sum").log1p().alias("y"),
    ).with_columns(
        # daytype for the baseline lookup
        pl.when(pl.col("is_public_holiday")).then(pl.lit("sun"))
          .when(pl.col("operating_day").dt.weekday() == 6).then(pl.lit("sat"))
          .when(pl.col("operating_day").dt.weekday() == 7).then(pl.lit("sun"))
          .otherwise(pl.lit("weekday")).alias("daytype"),
    )


def encode(df: pl.DataFrame, enc: dict | None) -> tuple[pl.DataFrame, dict]:
    """Integer-encode categoricals + fill numeric nulls. Builds encoders from the
    frame when enc is None (training); otherwise applies the given encoders."""
    if enc is None:
        stops = sorted(df["stop_code"].unique().to_list())
        enc = {
            "stop_map": {s: i for i, s in enumerate(stops)},
            "fills": {c: float(df[c].median() or 0.0) for c in NUMERIC_FILL},
        }
    unk = len(enc["stop_map"])
    out = df.with_columns(
        pl.col("stop_code").replace_strict(enc["stop_map"], default=unk).alias("stop_idx"),
        *[pl.col(c).cast(pl.Int8) for c in
          ["is_public_holiday", "is_school_holiday", "oth_in_session", "ur_in_session"]],
        *[pl.col(c).fill_null(enc["fills"][c]) for c in NUMERIC_FILL],
    )
    return out, enc


def to_xy(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    X = df.select(FEATURES_ALL).to_numpy()
    y = df["y"].to_numpy()
    return X, y


def baseline_mae(train: pl.DataFrame, val: pl.DataFrame) -> float:
    """(stop, hour, daytype) mean total-dwell lookup; global mean for unseen keys."""
    lut = train.group_by("stop_code", "hour", "daytype").agg(
        pl.col("dwell_sum").mean().alias("pred"))
    g = train["dwell_sum"].mean()
    j = val.join(lut, on=["stop_code", "hour", "daytype"], how="left").with_columns(
        pl.col("pred").fill_null(g))
    return float((j["pred"] - j["dwell_sum"]).abs().mean())


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the general-demand LightGBM model.")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if MODEL_OUT.exists() and not args.force:
        print(f"CACHED  {MODEL_OUT} exists — use --force to retrain")
        return
    if not FEATURES.exists():
        raise SystemExit(f"missing {FEATURES} — run assemble first")

    df = aggregate(load_clean())
    train_df = df.filter(pl.col("source_window") != VAL_WINDOW)
    val_df = df.filter(pl.col("source_window") == VAL_WINDOW)
    print(f"train {train_df.height:,} cells | val {val_df.height:,} (window {VAL_WINDOW})")

    train_enc, enc = encode(train_df, None)
    val_enc, _ = encode(val_df, enc)
    Xtr, ytr = to_xy(train_enc)
    Xva, yva = to_xy(val_enc)

    cat_idx = [FEATURES_ALL.index(c) for c in CATEGORICAL]
    dtr = lgb.Dataset(Xtr, ytr, feature_name=FEATURES_ALL, categorical_feature=cat_idx)
    dva = lgb.Dataset(Xva, yva, reference=dtr)
    params = {
        "objective": "regression", "metric": "l2", "learning_rate": 0.05,
        "num_leaves": 63, "min_data_in_leaf": 200, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 1, "verbosity": -1, "seed": 42,
    }
    model = lgb.train(params, dtr, num_boost_round=1500, valid_sets=[dva],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)])

    # validation error in real seconds
    pred_s = np.expm1(model.predict(Xva, num_iteration=model.best_iteration))
    true_s = np.expm1(yva)
    mae = float(np.abs(pred_s - true_s).mean())
    rmse = float(np.sqrt(((pred_s - true_s) ** 2).mean()))
    base = baseline_mae(train_df, val_df)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_OUT), num_iteration=model.best_iteration)
    ENC_OUT.write_text(json.dumps({
        "stop_map": enc["stop_map"], "fills": enc["fills"],
        "numeric": NUMERIC, "categorical": CATEGORICAL, "features": FEATURES_ALL,
        "dwell_cap_s": DWELL_CAP_S,
    }))

    print("\n" + "═" * 56)
    print("  DEMAND MODEL — validation (Oct-2024 window)")
    print("  target: total boarding-dwell per stop·hour [seconds]")
    print("═" * 56)
    print(f"  model   MAE {mae:7.1f}s   RMSE {rmse:7.1f}s")
    print(f"  lookup  MAE {base:7.1f}s   (stop×hour×daytype mean)")
    print(f"  lift    {(base - mae) / base * 100:+.1f}% MAE vs baseline")
    print("═" * 56)
    print(f"  saved {MODEL_OUT}  (best_iter {model.best_iteration})")


if __name__ == "__main__":
    main()
