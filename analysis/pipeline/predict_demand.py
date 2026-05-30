"""Day-ahead demand surface -> data/demand/demand_<date>.json.

Run the day before; get back, for every known stop, a per-tick pressure series
plus the event reason behind any surge. Output contract: docs/DEMAND_BUCKET_SCHEMA.md.

Two layers, summed (pressure_s = baseline_s + event_s):
  baseline  GBM (train_demand_model.py), event-free, deterministic features
            (no weather input) -> a clean "normal day" surface per (stop, hour).
  events    profile-driven kernel reading a HARDCODED demo feed (demo_events.json,
            NOT events_regensburg.parquet) + a curve library (kernel_profiles.json).
            One directional event (e.g. football) emits TWO legs: inbound pressure
            at the origin hub before the game (-> venue) and outbound pressure at
            the venue after it (-> origin). Same event_id links the two.

Resolution: the GBM is hourly (its native resolution); we expand to 15-min ticks
with the baseline hour-held, so the kernel can place event bumps sharply.

Idempotent: skips if the day file exists (--force to rebuild).

Usage:
    uv run python pipeline/predict_demand.py --date 2025-10-18
    uv run python pipeline/predict_demand.py --date 2025-10-18 --force
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date as Date
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

PARQUET = Path("data/parquet")
MODEL = Path("data/models/demand_lgbm.txt")
ENC = Path("data/models/demand_encoders.json")
OUT_DIR = Path("data/demand")

RES_MIN = 15
N_TICKS = 24 * 60 // RES_MIN  # 96
TICKS_PER_HOUR = 60 // RES_MIN  # 4

PROFILES = Path("pipeline/kernel_profiles.json")  # event_type -> curve library
DEMO_EVENTS = Path("pipeline/demo_events.json")    # hardcoded demo feed (NOT the parquet)


# ── calendar features (deterministic from the date) ──────────────────────────
def calendar_features(d: Date) -> dict:
    hol = pl.read_parquet(PARQUET / "holidays_bavaria.parquet").filter(pl.col("date") == d)
    uni = pl.read_parquet(PARQUET / "university_calendar.parquet").filter(pl.col("date") == d)
    day = pl.read_parquet(PARQUET / "daylight_regensburg.parquet").filter(pl.col("date") == d)

    def in_session(inst: str) -> int:
        r = uni.filter(pl.col("institution") == inst)
        return int(bool(r["in_session"][0])) if r.height else 0

    daylight = float(day["daylight_hours"][0]) if day.height else 12.0
    return {
        "daylight_hours": daylight,
        "is_public_holiday": int((hol["kind"] == "public").any()) if hol.height else 0,
        "is_school_holiday": int((hol["kind"] == "school").any()) if hol.height else 0,
        "oth_in_session": in_session("oth"),
        "ur_in_session": in_session("ur"),
    }


# ── baseline: GBM over (stop, hour) ──────────────────────────────────────────
def predict_baseline(d: Date, model: lgb.Booster, enc: dict) -> pl.DataFrame:
    """Returns stop_code + hourly baseline_s (24 rows per stop)."""
    stops = (
        pl.read_parquet(PARQUET / "stops_geo.parquet")
        .filter(pl.col("stop_code").is_in(list(enc["stop_map"].keys())))
        .select("stop_code", "stop_lat", "stop_lon")
    )
    grid = stops.join(pl.DataFrame({"hour": list(range(24))}), how="cross")
    cal = calendar_features(d)
    grid = grid.with_columns(
        pl.col("stop_code").replace_strict(enc["stop_map"]).alias("stop_idx"),
        pl.lit(d.isoweekday()).alias("dow"),
        (2 * np.pi * pl.col("hour") / 24).sin().alias("hour_sin"),
        (2 * np.pi * pl.col("hour") / 24).cos().alias("hour_cos"),
        **{k: pl.lit(v) for k, v in cal.items()},
    )
    X = grid.select(enc["features"]).to_numpy()
    pred_s = np.clip(np.expm1(model.predict(X)), 0, None)
    return grid.select("stop_code", "hour").with_columns(pl.Series("baseline_s", pred_s))


# ── events: profile-driven directional curves on per-event stops ─────────────
def _event_date(e: dict) -> Date:
    return datetime.fromisoformat(e["start"]).date()


def _minute_of_day(iso: str) -> int:
    """Wall-clock minute-of-day from an ISO 8601 datetime (offset is metadata; the
    96 ticks are local wall-clock, so we anchor on the local hour/minute)."""
    dt = datetime.fromisoformat(iso)
    return dt.hour * 60 + dt.minute


def _mmss(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _interp(keypoints: list[list[float]], x: float) -> float:
    """Linear interpolation over sorted [offset, level] keypoints; 0 outside range."""
    if x < keypoints[0][0] or x > keypoints[-1][0]:
        return 0.0
    for (x0, l0), (x1, l1) in zip(keypoints, keypoints[1:]):
        if x0 <= x <= x1:
            return l0 if x1 == x0 else l0 + (l1 - l0) * (x - x0) / (x1 - x0)
    return 0.0


# ── smooth double-logistic pulse: S-curve up × S-curve down ──────────────────
_PULSE_EPS = 0.02  # zero out levels below 2% of peak -> finite, clean support window


def _logistic(x: float, c: float, k: float) -> float:
    z = (x - c) / k
    if z < -40:
        return 0.0
    if z > 40:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _pulse(x: float, rise: dict, fall: dict) -> float:
    """level = sigmoid(rise) * (1 - sigmoid(fall)); smooth 0→1→0, asymmetric by design."""
    return _logistic(x, rise["center"], rise["k"]) * (1.0 - _logistic(x, fall["center"], fall["k"]))


def _pulse_max(rise: dict, fall: dict) -> float:
    """Reference peak over a wide minute grid — resolution-independent normalizer so the
    same wall-clock minute yields the same level at 1-min or 15-min sampling."""
    return max(_pulse(x, rise, fall) for x in range(-300, 301)) or 1.0


def leg_specs(d: Date) -> list[dict]:
    """Flatten the demo feed into resolution-agnostic leg specs — the single source of
    truth for both the 15-min surface and the 1-min curve export. An event names a
    `venue`, a `start`/`end`, and origin `stops` each with a `multiplier`; the type owns
    the curve. Per-leg peak = multiplier * scale_s. A directional event emits, PER origin
    stop, an inbound leg (stop→venue, anchored to start) and an outbound leg (venue→stop,
    anchored to end). A non-directional event emits one onsite leg per listed stop (or
    the venue), keypoints read as window fractions."""
    profiles = json.loads(PROFILES.read_text())
    events = [e for e in json.loads(DEMO_EVENTS.read_text()) if _event_date(e) == d]
    specs: list[dict] = []
    for e in events:
        prof = profiles[e["event_type"]]
        scale_s = float(prof["scale_s"])
        venue = e["event_stop"]
        start, end = _minute_of_day(e["start"]), _minute_of_day(e["end"])
        if prof.get("directional"):
            inb, outb = prof["inbound"], prof["outbound"]
            for o in e["origins"]:
                stop, mult = o["stop"], o["multiplier"]
                peak = mult * scale_s
                specs.append(dict(event=e, board_stop=stop, to_stop=venue, leg="inbound",
                                  multiplier=mult, curve=inb, peak=peak,
                                  anchor_min=start if inb["anchor"] == "start" else end))
                specs.append(dict(event=e, board_stop=venue, to_stop=stop, leg="outbound",
                                  multiplier=mult, curve=outb, peak=peak,
                                  anchor_min=end if outb["anchor"] == "end" else start))
        else:
            targets = e.get("origins") or [{"stop": venue, "multiplier": 1.0}]
            for o in targets:
                specs.append(dict(event=e, board_stop=o["stop"], to_stop=None, leg="onsite",
                                  multiplier=o["multiplier"], curve=prof,
                                  peak=o["multiplier"] * scale_s,
                                  anchor_min=start, span=max(1, end - start)))
    return specs


def _render(spec: dict, res_min: int) -> list[float]:
    """Sample a leg's curve onto a full day at res_min resolution. Onsite legs read the
    curve as fractions of the event window; directional legs as minute offsets. A curve is
    either a smooth `logistic_pulse` (shape key) or piecewise-linear `keypoints`."""
    n, curve, peak = 24 * 60 // res_min, spec["curve"], spec["peak"]
    if "span" in spec:  # onsite: x = fraction through the window (keypoints only)
        a, span = spec["anchor_min"], spec["span"]
        return [round(_interp(curve["keypoints"], (t * res_min - a) / span) * peak, 1)
                for t in range(n)]
    a = spec["anchor_min"]  # directional: x = minutes relative to anchor
    if curve.get("shape") == "logistic_pulse":
        rise, fall = curve["rise"], curve["fall"]
        pmax = _pulse_max(rise, fall)
        out = []
        for t in range(n):
            lvl = _pulse(t * res_min - a, rise, fall) / pmax
            out.append(round(lvl * peak, 1) if lvl >= _PULSE_EPS else 0.0)
        return out
    return [round(_interp(curve["keypoints"], t * res_min - a) * peak, 1) for t in range(n)]


def event_bumps(specs: list[dict], valid_stops: set[str]) -> dict[str, list[dict]]:
    """board stop_code -> list of event contributions at the surface resolution (15-min)."""
    out: dict[str, list[dict]] = {}
    for s in specs:
        if s["board_stop"] not in valid_stops:
            continue
        series = _render(s, RES_MIN)
        active = [t for t, v in enumerate(series) if v > 0]
        if not active:
            continue
        e = s["event"]
        out.setdefault(s["board_stop"], []).append({
            "event_id": e["event_id"], "event_label": e["event_label"],
            "leg": s["leg"], "to": s["to_stop"], "multiplier": s["multiplier"],
            "active_ticks": active, "contribution_s": series,
        })
    return out


def event_curves(d: Date, specs: list[dict], valid_stops: set[str], res_min: int = 1) -> dict:
    """Event-first companion artifact: per event, one pressure curve per leg, sampled at
    res_min (default 1-min) and windowed to its active span — for the frontend charts.
    Each leg ships BOTH `pressure_s` (absolute boarding-dwell seconds) and `pressure_norm`
    (the same normalized 0–1 vs its own peak). The x-axis is implicit: time[i] = start +
    i*res_min. A leg = one directional flow (from -> to) = one flex-bus run."""
    by_event: dict[str, dict] = {}
    for s in specs:
        if s["board_stop"] not in valid_stops:
            continue
        series = _render(s, res_min)
        active = [i for i, v in enumerate(series) if v > 0]
        if not active:
            continue
        lo, hi = active[0], active[-1]
        window = series[lo:hi + 1]
        peak_s = max(window) or 1.0
        e = s["event"]
        ev = by_event.setdefault(e["event_id"], {
            "event_id": e["event_id"], "label": e["event_label"],
            "type": e["event_type"], "venue": e["event_stop"],
            "event_start": _mmss(_minute_of_day(e["start"])),   # kickoff
            "event_end": _mmss(_minute_of_day(e["end"])),       # whistle
            "stops": [],   # every stop with a curve from this event (map highlight)
            "legs": [],
        })
        ev["legs"].append({
            "from": s["board_stop"], "to": s["to_stop"],
            "start": _mmss(lo * res_min),   # pressure ramps up
            "end": _mmss(hi * res_min),     # pressure dies out
            "peak_s": round(peak_s, 1),     # absolute peak (= pressure_s max = pressure_norm's 1.0)
            "pressure_s": window,           # absolute boarding-dwell seconds, one per tick
            "pressure_norm": [round(v / peak_s, 4) for v in window],  # same, normalized 0–1 vs peak_s
        })

    for ev in by_event.values():
        ev["stops"] = sorted({leg["from"] for leg in ev["legs"]})
    return {"date": d.isoformat(), "resolution_min": res_min, "events": list(by_event.values())}


# ── assemble the locked JSON ─────────────────────────────────────────────────
def build(d: Date) -> tuple[dict, dict]:
    """Returns (surface, curves): the node-keyed 15-min surface and the event-first
    1-min curve export, both derived from one set of leg specs."""
    model = lgb.Booster(model_file=str(MODEL))
    enc = json.loads(ENC.read_text())
    valid_stops = set(enc["stop_map"].keys())

    specs = leg_specs(d)
    base = predict_baseline(d, model, enc)
    bumps = event_bumps(specs, valid_stops)
    coords = {
        r["stop_code"]: (r["stop_lat"], r["stop_lon"])
        for r in pl.read_parquet(PARQUET / "stops_geo.parquet").iter_rows(named=True)
    }

    tick_times = [f"{t * RES_MIN // 60:02d}:{t * RES_MIN % 60:02d}" for t in range(N_TICKS)]
    nodes, global_max = [], 0.0
    for stop in sorted(valid_stops):
        hourly = base.filter(pl.col("stop_code") == stop).sort("hour")["baseline_s"].to_list()
        if not hourly:
            continue
        baseline_s = [round(hourly[t // TICKS_PER_HOUR], 1) for t in range(N_TICKS)]
        events = bumps.get(stop, [])
        event_s = [round(sum(e["contribution_s"][t] for e in events), 1) for t in range(N_TICKS)]
        pressure_s = [round(baseline_s[t] + event_s[t], 1) for t in range(N_TICKS)]
        global_max = max(global_max, max(pressure_s))
        lat, lon = coords.get(stop, (None, None))
        nodes.append({
            "stop_code": stop,
            "lat": lat,
            "lon": lon,
            "pressure_s": pressure_s,
            "pressure_norm": pressure_s,  # placeholder; normalized below once global_max known
            "baseline_s": baseline_s,
            "event_s": event_s,
            "events": events,
        })

    denom = global_max or 1.0
    for n in nodes:
        n["pressure_norm"] = [round(p / denom, 4) for p in n["pressure_s"]]

    surface = {
        "date": d.isoformat(),
        "resolution_min": RES_MIN,
        "n_ticks": N_TICKS,
        "tick_times": tick_times,
        "nodes": nodes,
    }
    return surface, event_curves(d, specs, valid_stops)


def main() -> None:
    ap = argparse.ArgumentParser(description="Predict a day-ahead demand surface.")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    d = Date.fromisoformat(args.date)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"demand_{d.isoformat()}.json"
    curves_path = OUT_DIR / f"demand_{d.isoformat()}_events.json"
    if out_path.exists() and not args.force:
        print(f"CACHED  {out_path} exists — use --force to rebuild")
        return
    if not MODEL.exists():
        raise SystemExit(f"missing {MODEL} — run train_demand_model.py first")

    surface, curves = build(d)
    out_path.write_text(json.dumps(surface, separators=(",", ":")))
    curves_path.write_text(json.dumps(curves, separators=(",", ":")))
    n_ev = sum(len(n["events"]) for n in surface["nodes"])
    n_legs = sum(len(e["legs"]) for e in curves["events"])
    print(f"wrote {out_path}  ({len(surface['nodes'])} stops, {n_ev} event bumps)")
    print(f"wrote {curves_path}  ({len(curves['events'])} events, {n_legs} legs @ "
          f"{curves['resolution_min']}-min)")


if __name__ == "__main__":
    main()
