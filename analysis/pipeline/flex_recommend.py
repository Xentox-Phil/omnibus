"""Flex-bus recommendation engine and scenario GTFS generator.

Consumes directional stop pressure predictions and chooses terminal-available
flex buses from low-pressure donor routes. Outputs:

  data/scenarios/<scenario_id>/recommendations.json
  data/scenarios/<scenario_id>/scenario_gtfs.zip
  data/scenarios/<scenario_id>/pressure_input.json
  data/scenarios/<scenario_id>/fleet_snapshot.json

The generated GTFS is a complete scenario feed: base RVV GTFS files copied from
data/raw/gtfs plus appended trips on existing public routes and one operational
OUT route for unboardable repositioning. It does not overwrite the real RVV feed.

Usage from analysis/:
    uv run python pipeline/flex_recommend.py
    uv run python pipeline/flex_recommend.py --pressure-json path/to/pressure.json
    uv run python pipeline/flex_recommend.py --scenario-id jahn_match_demo --force
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

PARQUET = Path("data/parquet")
FEATURES = PARQUET / "features.parquet"
RAW_GTFS = Path("data/raw/gtfs")
OUT_ROOT = Path("data/scenarios")
SERVICE_AGENCY_ID = "OMNIBUS"
OUT_OF_SERVICE_ROUTE_ID = "OUT_OF_SERVICE"
OUT_OF_SERVICE_ROUTE_SHORT_NAME = "OUT"

# Demo assumptions for data RVV did not provide in the challenge bundle. Keep
# these explicit so they can be replaced by real AVL/fleet metadata later.
MOCK_FLEET: list[dict[str, Any]] = [
    {
        "bus_id": "FLEX_10_02",
        "home_route": "10",
        "capacity": 90,
        "flex_capable": True,
        "status": "route_end",
        "terminal_stop_name": "Königswiesen",
        "available_at": "2025-05-11T16:36:00",
        "next_regular_trip_id": "MOCK_10_1645_KOENIGSWIESEN_IRLER_HOEHE",
    },
    {
        "bus_id": "FLEX_1_04",
        "home_route": "1",
        "capacity": 90,
        "flex_capable": True,
        "status": "route_start",
        "terminal_stop_name": "Prüfening",
        "available_at": "2025-05-11T17:32:00",
        "next_regular_trip_id": "MOCK_1_1740_PRUEFENING_POMMERNSTR",
    },
    {
        "bus_id": "FLEX_11_03",
        "home_route": "11",
        "capacity": 90,
        "flex_capable": True,
        "status": "mid_route",
        "terminal_stop_name": "Hauptbahnhof",
        "available_at": "2025-05-11T18:18:00",
        "next_regular_trip_id": "MOCK_11_MID_ROUTE",
    },
    {
        "bus_id": "BUS_6_09",
        "home_route": "6",
        "capacity": 90,
        "flex_capable": False,
        "status": "route_end",
        "terminal_stop_name": "Klinikum",
        "available_at": "2025-05-11T17:28:00",
        "next_regular_trip_id": "MOCK_6_NON_FLEX",
    },
    {
        "bus_id": "FLEX_10_05",
        "home_route": "10",
        "capacity": 90,
        "flex_capable": True,
        "status": "route_end",
        "terminal_stop_name": "An der Irler Höhe",
        "available_at": "2025-05-11T20:08:00",
        "next_regular_trip_id": "MOCK_10_2015_IRLER_HOEHE_KOENIGSWIESEN",
    },
    {
        "bus_id": "FLEX_10_07",
        "home_route": "10",
        "capacity": 90,
        "flex_capable": True,
        "status": "route_end",
        "terminal_stop_name": "K\u00f6nigswiesen",
        "available_at": "2025-05-11T22:18:00",
        "next_regular_trip_id": "MOCK_10_2225_KOENIGSWIESEN_IRLER_HOEHE",
    },
]

ROUTE_CONSTRAINTS: dict[str, dict[str, Any]] = {
    # active_buses is mocked fleet state, not a claim from RVV data.
    "1": {"min_buses_active": 10, "active_buses": 13, "can_donate": True},
    "4": {"min_buses_active": 6, "active_buses": 7, "can_donate": False},
    "6": {"min_buses_active": 8, "active_buses": 10, "can_donate": False},
    "10": {"min_buses_active": 3, "active_buses": 5, "can_donate": True},
    "11": {"min_buses_active": 7, "active_buses": 8, "can_donate": False},
}


@dataclass(frozen=True)
class PressurePrediction:
    time_bucket: datetime
    origin_stop_name: str
    destination_stop_name: str
    pressure: float
    confidence: float
    reason: str
    expected_duration_min: int = 45


@dataclass(frozen=True)
class Stop:
    stop_id: str
    stop_code: str
    stop_name: str
    stop_lat: float
    stop_lon: float


@dataclass(frozen=True)
class Mission:
    mission_id: str
    start_time: datetime
    end_time: datetime
    stops: list[str]
    pressure_relieved: float
    confidence: float
    reason: str
    pressure_ids: list[str]


@dataclass(frozen=True)
class DonorCandidate:
    bus_id: str
    home_route: str
    capacity: int
    terminal_stop_name: str
    available_at: datetime
    status: str
    donor_route_damage: float
    pullability_score: float
    next_regular_trip_id: str


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def slug(value: str, limit: int = 42) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    cleaned = cleaned or "ITEM"
    return cleaned[:limit].strip("_") or "ITEM"


def stable_stop_id(stop_name: str) -> str:
    digest = hashlib.sha1(stop_name.encode("utf-8")).hexdigest()[:8]
    return f"STOP_{slug(stop_name, 24)}_{digest}"


def normalise_name(value: str) -> str:
    return (
        value.lower()
        .replace("ß", "ss")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ä", "a")
        .replace("Ü", "u")
        .replace("Ö", "o")
        .replace("Ä", "a")
    )


def strip_platform(value: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def haversine_km(a: Stop, b: Stop) -> float:
    radius = 6371.0
    lat1, lon1 = math.radians(a.stop_lat), math.radians(a.stop_lon)
    lat2, lon2 = math.radians(b.stop_lat), math.radians(b.stop_lon)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def estimate_travel_min(a: Stop, b: Stop) -> int:
    if a.stop_name == b.stop_name:
        return 0
    # Conservative city-bus movement including signals and stop approach time.
    return max(4, math.ceil((haversine_km(a, b) / 18.0) * 60 + 4))


def load_base_gtfs_stops() -> list[Stop]:
    path = RAW_GTFS / "stops.txt"
    if not path.exists():
        return []
    _, rows = read_csv_rows(path)
    stops: list[Stop] = []
    for row in rows:
        if not row.get("stop_lat") or not row.get("stop_lon"):
            continue
        try:
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
        except ValueError:
            continue
        stops.append(
            Stop(
                stop_id=row["stop_id"],
                stop_code=row.get("stop_code") or row.get("parent_station") or "",
                stop_name=row["stop_name"],
                stop_lat=lat,
                stop_lon=lon,
            )
        )
    return stops


def match_base_stop(feature_stop: Stop, base_stops: list[Stop]) -> Stop:
    if not base_stops:
        return feature_stop

    ours = normalise_name(feature_stop.stop_name)
    ours_base = normalise_name(strip_platform(feature_stop.stop_name))

    best_named: tuple[int, float, Stop] | None = None
    for candidate in base_stops:
        theirs = normalise_name(candidate.stop_name)
        theirs_base = normalise_name(strip_platform(candidate.stop_name))
        score = 0
        if ours == theirs or ours_base == theirs_base:
            score = 3
        elif ours_base and (ours_base in theirs or theirs_base in ours):
            score = 2
        elif feature_stop.stop_code and feature_stop.stop_code == candidate.stop_code:
            score = 2
        if score:
            distance = haversine_km(feature_stop, candidate)
            if best_named is None or (score, -distance) > (best_named[0], -best_named[1]):
                best_named = (score, distance, candidate)

    if best_named and best_named[1] <= 1.5:
        candidate = best_named[2]
        return Stop(
            stop_id=candidate.stop_id,
            stop_code=feature_stop.stop_code,
            stop_name=feature_stop.stop_name,
            stop_lat=candidate.stop_lat,
            stop_lon=candidate.stop_lon,
        )

    nearest = min(base_stops, key=lambda candidate: haversine_km(feature_stop, candidate))
    if haversine_km(feature_stop, nearest) <= 0.35:
        return Stop(
            stop_id=nearest.stop_id,
            stop_code=feature_stop.stop_code,
            stop_name=feature_stop.stop_name,
            stop_lat=nearest.stop_lat,
            stop_lon=nearest.stop_lon,
        )

    return feature_stop


def load_stop_lookup() -> dict[str, Stop]:
    if not FEATURES.exists():
        raise SystemExit(f"{FEATURES} missing. Run pipeline/run.py first.")

    rows = (
        pl.scan_parquet(FEATURES)
        .filter(
            pl.col("stop_name").is_not_null()
            & pl.col("stop_lat").is_not_null()
            & pl.col("stop_lon").is_not_null()
        )
        .group_by("stop_name", "stop_code", "stop_lat", "stop_lon")
        .len()
        .sort("len", descending=True)
        .unique(subset=["stop_name"], keep="first")
        .select("stop_name", "stop_code", "stop_lat", "stop_lon")
        .collect()
    )
    base_stops = load_base_gtfs_stops()
    result: dict[str, Stop] = {}
    for r in rows.iter_rows(named=True):
        feature_stop = Stop(
            stop_id=stable_stop_id(r["stop_name"]),
            stop_code=r["stop_code"] or "",
            stop_name=r["stop_name"],
            stop_lat=float(r["stop_lat"]),
            stop_lon=float(r["stop_lon"]),
        )
        result[r["stop_name"]] = match_base_stop(feature_stop, base_stops)
    return result


def stop_lookup_by_code(stops: dict[str, Stop]) -> dict[str, Stop]:
    return {stop.stop_code: stop for stop in stops.values() if stop.stop_code}


def resolve_stop_name(value: str, stops: dict[str, Stop], by_code: dict[str, Stop]) -> str:
    if value in stops:
        return value
    if value in by_code:
        return by_code[value].stop_name
    raise KeyError(value)


def load_route_sequences() -> dict[str, list[list[str]]]:
    """Representative stop sequences per line/direction from the RVV feature table."""
    trips = (
        pl.scan_parquet(FEATURES)
        .filter(pl.col("stop_name").is_not_null() & pl.col("trip_id").is_not_null())
        .group_by("line", "direction", "trip_id")
        .agg(
            pl.col("stop_name").sort_by("stop_seq").alias("stops"),
            pl.len().alias("n_stops"),
        )
        .filter(pl.col("n_stops") >= 3)
        .with_columns(pl.col("stops").list.join(" > ").alias("_signature"))
        .group_by("line", "direction", "_signature")
        .agg(pl.len().alias("trip_count"), pl.col("stops").first().alias("stops"))
        .sort("trip_count", descending=True)
        .collect()
    )

    routes: dict[str, list[list[str]]] = {}
    seen: set[tuple[str, str]] = set()
    for row in trips.iter_rows(named=True):
        key = (row["line"], row["direction"])
        if key in seen:
            continue
        seen.add(key)
        routes.setdefault(row["line"], []).append(list(row["stops"]))
    return routes


def demo_pressures() -> list[PressurePrediction]:
    return [
        PressurePrediction(
            time_bucket=parse_dt("2024-10-19T20:30:00"),
            origin_stop_name="Hauptbahnhof",
            destination_stop_name="Jahnstadion Regensburg",
            pressure=0.91,
            confidence=0.88,
            reason="Jahn event wave; central transfer pressure toward stadium.",
            expected_duration_min=50,
        ),
        PressurePrediction(
            time_bucket=parse_dt("2024-10-19T20:30:00"),
            origin_stop_name="Dachauplatz",
            destination_stop_name="Jahnstadion Regensburg",
            pressure=0.63,
            confidence=0.79,
            reason="Altstadt pickup pressure joins the stadium wave.",
            expected_duration_min=45,
        ),
        PressurePrediction(
            time_bucket=parse_dt("2024-10-19T22:30:00"),
            origin_stop_name="Jahnstadion Regensburg",
            destination_stop_name="Hauptbahnhof",
            pressure=0.95,
            confidence=0.91,
            reason="Post-match crowd wave toward HBF.",
            expected_duration_min=55,
        ),
    ]


def as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def tick_datetime(day: date, tick_time: str) -> datetime:
    hour, minute = tick_time.split(":")[:2]
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=int(hour), minutes=int(minute))


def peak_value(values: list[Any], ticks: list[int], default: float = 0.0) -> tuple[int, float]:
    best_tick = ticks[0]
    best_value = default
    for tick in ticks:
        if tick < 0 or tick >= len(values):
            continue
        value = as_float(values[tick])
        if value is not None and value >= best_value:
            best_tick = tick
            best_value = value
    return best_tick, best_value


def load_dense_pressure_format(raw: dict[str, Any], stops: dict[str, Stop]) -> list[PressurePrediction]:
    """Parse the teammate's dense node/tick pressure handoff format.

    The current format is destination-node-centric. For event pressure at JAHN,
    we create an inbound mission from HBF/Dachauplatz to JAHN at the early event
    peak and an outbound mission from JAHN to HBF at the late event peak.
    """
    by_code = stop_lookup_by_code(stops)
    service_day = date.fromisoformat(raw["date"])
    tick_times = raw["tick_times"]
    predictions: list[PressurePrediction] = []

    for node in raw.get("nodes", []):
        stop_ref = node.get("stop_code") or node.get("stop_name")
        if not stop_ref:
            continue
        try:
            node_stop = resolve_stop_name(stop_ref, stops, by_code)
        except KeyError:
            # If the model uses a code we cannot map yet, skip it rather than
            # creating a GTFS stop with no relationship to the RVV data.
            continue

        pressure_norm = node.get("pressure_norm", [])
        event_s = node.get("event_s", [])
        node_code = str(node.get("stop_code", "")).upper()

        for event in node.get("events", []):
            active_ticks = [int(t) for t in event.get("active_ticks", []) if 0 <= int(t) < len(tick_times)]
            if not active_ticks:
                active_ticks = [
                    idx for idx, value in enumerate(event_s)
                    if as_float(value) is not None and as_float(value) > 0
                ]
            if not active_ticks:
                continue

            if event.get("to"):
                try:
                    destination_stop = resolve_stop_name(str(event["to"]), stops, by_code)
                except KeyError:
                    continue
                contribution = event.get("contribution_s", event_s)
                event_label = event.get("event_label") or event.get("event_id") or "event pressure"
                peak_tick, _ = peak_value(contribution, active_ticks)
                _, pressure = peak_value(pressure_norm, active_ticks, default=0.5)
                leg = str(event.get("leg", "")).lower()
                predictions.append(
                    PressurePrediction(
                        time_bucket=tick_datetime(service_day, tick_times[peak_tick]),
                        origin_stop_name=node_stop,
                        destination_stop_name=destination_stop,
                        pressure=clamp(pressure),
                        confidence=clamp(float(event.get("multiplier", 0.9)), hi=0.95),
                        reason=f"{event_label}: {leg or 'event'} pressure {node_stop} -> {destination_stop}.",
                        expected_duration_min=55 if leg == "outbound" else 50,
                    )
                )
                continue

            midpoint = len(active_ticks) // 2
            inbound_ticks = active_ticks[: max(1, midpoint)]
            outbound_ticks = active_ticks[midpoint:] or active_ticks[-1:]
            contribution = event.get("contribution_s", event_s)
            event_label = event.get("event_label") or event.get("event_id") or "event pressure"

            inbound_tick, _ = peak_value(contribution, inbound_ticks)
            _, inbound_pressure = peak_value(pressure_norm, inbound_ticks, default=0.5)
            outbound_tick, _ = peak_value(contribution, outbound_ticks)
            _, outbound_pressure = peak_value(pressure_norm, outbound_ticks, default=0.5)

            if node_code == "JAHN" or "jahn" in node_stop.lower():
                predictions.extend(
                    [
                        PressurePrediction(
                            time_bucket=tick_datetime(service_day, tick_times[inbound_tick]),
                            origin_stop_name="Hauptbahnhof",
                            destination_stop_name=node_stop,
                            pressure=clamp(inbound_pressure),
                            confidence=0.88,
                            reason=f"{event_label}: inbound event pressure toward {node_stop}.",
                            expected_duration_min=50,
                        ),
                        PressurePrediction(
                            time_bucket=tick_datetime(service_day, tick_times[inbound_tick]),
                            origin_stop_name="Dachauplatz",
                            destination_stop_name=node_stop,
                            pressure=clamp(inbound_pressure * 0.7),
                            confidence=0.78,
                            reason=f"{event_label}: Altstadt pickup pressure toward {node_stop}.",
                            expected_duration_min=45,
                        ),
                        PressurePrediction(
                            time_bucket=tick_datetime(service_day, tick_times[outbound_tick]),
                            origin_stop_name=node_stop,
                            destination_stop_name="Hauptbahnhof",
                            pressure=clamp(outbound_pressure),
                            confidence=0.90,
                            reason=f"{event_label}: outbound crowd wave from {node_stop} to HBF.",
                            expected_duration_min=55,
                        ),
                    ]
                )
            else:
                # Generic event destination fallback.
                predictions.append(
                    PressurePrediction(
                        time_bucket=tick_datetime(service_day, tick_times[inbound_tick]),
                        origin_stop_name="Hauptbahnhof",
                        destination_stop_name=node_stop,
                        pressure=clamp(inbound_pressure),
                        confidence=0.80,
                        reason=f"{event_label}: event pressure toward {node_stop}.",
                        expected_duration_min=45,
                    )
                )

    return sorted(predictions, key=lambda p: p.time_bucket)


def load_pressures(path: Path | None, stops: dict[str, Stop]) -> list[PressurePrediction]:
    if path is None:
        return demo_pressures()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and {"date", "tick_times", "nodes"} <= set(raw.keys()):
        pressures = load_dense_pressure_format(raw, stops)
        if not pressures:
            raise SystemExit("dense pressure file parsed successfully but produced no actionable pressures")
        return pressures
    if isinstance(raw, dict):
        raw = raw.get("pressures", [])
    return [
        PressurePrediction(
            time_bucket=parse_dt(item["time_bucket"]),
            origin_stop_name=item.get("origin_stop_name") or item["origin_stop"],
            destination_stop_name=item.get("destination_stop_name") or item["destination_stop"],
            pressure=float(item["pressure"]),
            confidence=float(item.get("confidence", 0.75)),
            reason=item.get("reason", "Directional pressure prediction."),
            expected_duration_min=int(item.get("expected_duration_min", 45)),
        )
        for item in raw
    ]


def route_serves_pressure(route_sequences: list[list[str]], pressure: PressurePrediction) -> bool:
    for seq in route_sequences:
        try:
            origin_idx = seq.index(pressure.origin_stop_name)
            dest_idx = seq.index(pressure.destination_stop_name)
        except ValueError:
            continue
        if origin_idx < dest_idx:
            return True
    return False


def route_pressure_by_line(
    route_sequences: dict[str, list[list[str]]], pressures: list[PressurePrediction]
) -> dict[str, float]:
    result: dict[str, float] = {}
    for line, seqs in route_sequences.items():
        served = [p.pressure * p.confidence for p in pressures if route_serves_pressure(seqs, p)]
        result[line] = clamp(sum(served) / 2.0)
    return result


def build_missions(pressures: list[PressurePrediction], stops: dict[str, Stop]) -> list[Mission]:
    missing = {
        name
        for p in pressures
        for name in (p.origin_stop_name, p.destination_stop_name)
        if name not in stops
    }
    if missing:
        raise SystemExit(f"pressure references stop(s) without coordinates: {sorted(missing)}")

    groups: dict[tuple[datetime, str, str], list[PressurePrediction]] = {}
    for p in pressures:
        # Same destination and bucket -> one inbound mission. Same origin and
        # bucket -> one outbound mission. The stronger group wins naturally.
        key = (p.time_bucket, p.destination_stop_name, "to_destination")
        if p.destination_stop_name == "Hauptbahnhof":
            key = (p.time_bucket, p.origin_stop_name, "from_origin")
        groups.setdefault(key, []).append(p)

    missions: list[Mission] = []
    for idx, grouped in enumerate(groups.values(), start=1):
        primary = max(grouped, key=lambda p: p.pressure * p.confidence)
        if primary.destination_stop_name == "Hauptbahnhof":
            route_stops = [primary.origin_stop_name, primary.destination_stop_name]
        else:
            # Keep the strongest origin first so the story stays legible
            # (e.g. HBF -> Jahnstadion), then pick up weaker compatible origins.
            other_origins = sorted(
                {p.origin_stop_name for p in grouped if p.origin_stop_name != primary.origin_stop_name},
                key=lambda name: haversine_km(stops[name], stops[primary.destination_stop_name]),
                reverse=True,
            )
            route_stops = [primary.origin_stop_name, *other_origins, primary.destination_stop_name]

        total_pressure = clamp(sum(p.pressure * p.confidence for p in grouped) / max(1.0, len(grouped) * 0.9))
        confidence = sum(p.confidence for p in grouped) / len(grouped)
        reasons = " | ".join(dict.fromkeys(p.reason for p in grouped))
        mission_id = f"MISSION_{primary.time_bucket:%H%M}_{idx}_{slug(route_stops[0], 10)}_{slug(route_stops[-1], 10)}"
        missions.append(
            Mission(
                mission_id=mission_id,
                start_time=primary.time_bucket,
                end_time=primary.time_bucket + timedelta(minutes=primary.expected_duration_min),
                stops=route_stops,
                pressure_relieved=total_pressure,
                confidence=confidence,
                reason=reasons,
                pressure_ids=[
                    f"{p.time_bucket.isoformat()}::{p.origin_stop_name}->{p.destination_stop_name}"
                    for p in grouped
                ],
            )
        )
    return sorted(missions, key=lambda m: (m.start_time, -m.pressure_relieved))


def build_donor_candidates(
    fleet: list[dict[str, Any]],
    route_pressure: dict[str, float],
    service_day: date,
) -> tuple[list[DonorCandidate], list[dict[str, Any]]]:
    donors: list[DonorCandidate] = []
    rejected: list[dict[str, Any]] = []
    for bus in fleet:
        route = str(bus["home_route"])
        constraints = ROUTE_CONSTRAINTS.get(route, {"min_buses_active": 1, "active_buses": 1, "can_donate": False})
        reasons: list[str] = []

        if not bus.get("flex_capable", False):
            reasons.append("not flex-capable")
        if bus.get("status") not in {"route_start", "route_end"}:
            reasons.append("bus is mid-route; terminal-only pull rule")
        if not constraints.get("can_donate", False):
            reasons.append("route marked protected from donation")
        if int(constraints.get("active_buses", 0)) - 1 < int(constraints.get("min_buses_active", 1)):
            reasons.append("would violate minimum active service")

        pressure = route_pressure.get(route, 0.0)
        if pressure >= 0.55:
            reasons.append(f"donor route has high served pressure ({pressure:.2f})")

        if reasons:
            rejected.append({"bus_id": bus["bus_id"], "home_route": route, "reasons": reasons})
            continue

        donor_damage = clamp(0.25 + pressure * 0.65)
        excess = max(0, int(constraints.get("active_buses", 0)) - int(constraints.get("min_buses_active", 1)))
        pullability = clamp(0.35 + excess * 0.15 - donor_damage * 0.35)
        donors.append(
            DonorCandidate(
                bus_id=bus["bus_id"],
                home_route=route,
                capacity=int(bus["capacity"]),
                terminal_stop_name=bus["terminal_stop_name"],
                available_at=datetime.combine(service_day, parse_dt(bus["available_at"]).time()),
                status=bus["status"],
                donor_route_damage=donor_damage,
                pullability_score=pullability,
                next_regular_trip_id=bus.get("next_regular_trip_id", ""),
            )
        )
    return donors, rejected


def score_pair(donor: DonorCandidate, mission: Mission, stops: dict[str, Stop]) -> tuple[float, dict[str, Any]]:
    terminal = stops[donor.terminal_stop_name]
    first_stop = stops[mission.stops[0]]
    reposition_min = estimate_travel_min(terminal, first_stop)
    reposition_arrival = donor.available_at + timedelta(minutes=reposition_min)
    late_min = max(0.0, (reposition_arrival - mission.start_time).total_seconds() / 60)
    early_wait_min = max(0.0, (mission.start_time - reposition_arrival).total_seconds() / 60)
    # Being too late is bad, but pulling a bus absurdly early also has an
    # opportunity cost. Ten minutes of staging is fine; hours of waiting is not.
    early_penalty_min = max(0.0, early_wait_min - 10.0)
    timing = clamp(1.0 - late_min / 25.0 - early_penalty_min / 90.0)
    capacity_added = clamp(donor.capacity / 100.0)

    score = (
        0.40 * mission.pressure_relieved
        + 0.20 * timing
        + 0.15 * mission.confidence
        + 0.15 * capacity_added
        + 0.10 * donor.pullability_score
        - 0.10 * donor.donor_route_damage
    )
    return clamp(score), {
        "reposition_min": reposition_min,
        "reposition_arrival": reposition_arrival.isoformat(timespec="seconds"),
        "late_min": round(late_min, 1),
        "early_wait_min": round(early_wait_min, 1),
        "timing_score": round(timing, 3),
    }


def allocate(
    missions: list[Mission],
    donors: list[DonorCandidate],
    stops: dict[str, Stop],
) -> list[dict[str, Any]]:
    assigned_buses: set[str] = set()
    recommendations: list[dict[str, Any]] = []
    for mission in missions:
        scored: list[tuple[float, DonorCandidate, dict[str, Any]]] = []
        for donor in donors:
            if donor.bus_id in assigned_buses:
                continue
            score, details = score_pair(donor, mission, stops)
            if details["timing_score"] <= 0:
                continue
            scored.append((score, donor, details))

        if not scored:
            recommendations.append(
                {
                    "recommendation_id": f"REC_{mission.mission_id}_UNASSIGNED",
                    "action": "no_feasible_terminal_bus",
                    "mission": asdict(mission),
                    "explanation": "No flex-capable bus is available at a route start/end in time for this pressure bucket.",
                }
            )
            continue

        score, donor, details = max(scored, key=lambda item: item[0])
        assigned_buses.add(donor.bus_id)
        transition_depart = donor.available_at
        transition_arrive = parse_dt(details["reposition_arrival"])
        flex_depart = max(mission.start_time, transition_arrive)
        flex_arrive = route_stop_times(mission.stops, flex_depart, stops)[-1]
        rec_id = f"REC_{mission.mission_id}_{donor.bus_id}"
        recommendations.append(
            {
                "recommendation_id": rec_id,
                "action": "reallocate_flex_bus",
                "score": round(score, 3),
                "bus_id": donor.bus_id,
                "from_route_id": donor.home_route,
                "cancelled_next_regular_trip_id": donor.next_regular_trip_id,
                "pull_point": {
                    "type": donor.status,
                    "stop_name": donor.terminal_stop_name,
                    "available_at": donor.available_at.isoformat(timespec="seconds"),
                },
                "deadhead": {
                    "from_stop": donor.terminal_stop_name,
                    "to_stop": mission.stops[0],
                    "depart": transition_depart.isoformat(timespec="seconds"),
                    "arrive": transition_arrive.isoformat(timespec="seconds"),
                    "duration_min": details["reposition_min"],
                },
                "new_flex_route": {
                    "route_id": f"FLEX_{slug(mission.stops[0], 12)}_{slug(mission.stops[-1], 12)}_{mission.start_time:%H%M}",
                    "stops": mission.stops,
                    "desired_depart": mission.start_time.isoformat(timespec="seconds"),
                    "depart": flex_depart.isoformat(timespec="seconds"),
                    "arrive": flex_arrive.isoformat(timespec="seconds"),
                },
                "mission": asdict(mission),
                "score_details": details,
                "explanation": (
                    f"{donor.bus_id} is flex-capable and available at {donor.status.replace('_', ' ')} "
                    f"{donor.terminal_stop_name}; route {donor.home_route} has low served pressure, "
                    f"while {mission.stops[0]} -> {mission.stops[-1]} pressure is high."
                ),
            }
        )
    return recommendations


def route_stop_times(stops_for_trip: list[str], start: datetime, stop_lookup: dict[str, Stop]) -> list[datetime]:
    times = [start]
    for prev, current in zip(stops_for_trip, stops_for_trip[1:]):
        times.append(times[-1] + timedelta(minutes=estimate_travel_min(stop_lookup[prev], stop_lookup[current])))
    return times


def route_stop_times_ending_at(
    stops_for_trip: list[str], end: datetime, stop_lookup: dict[str, Stop]
) -> list[datetime]:
    if len(stops_for_trip) <= 1:
        return [end]
    durations = [
        estimate_travel_min(stop_lookup[prev], stop_lookup[current])
        for prev, current in zip(stops_for_trip, stops_for_trip[1:])
    ]
    start = end - timedelta(minutes=sum(durations))
    return route_stop_times(stops_for_trip, start, stop_lookup)


def donor_regular_sequence(
    rec: dict[str, Any],
    route_sequences: dict[str, list[list[str]]],
    stop_lookup: dict[str, Stop],
) -> list[str]:
    terminal = rec["pull_point"]["stop_name"]
    route_id = rec["from_route_id"]
    seqs = route_sequences.get(route_id, [])
    if rec["pull_point"]["type"] == "route_end":
        candidates = [seq for seq in seqs if seq and seq[-1] == terminal]
    else:
        candidates = [seq for seq in seqs if seq and seq[0] == terminal]
    if not candidates:
        candidates = seqs[:1]
    if not candidates:
        return [terminal]
    # Drop stops without coordinates so the scenario GTFS remains loadable.
    return [name for name in max(candidates, key=len) if name in stop_lookup]


def enrich_recommendations_with_donor_trips(
    recommendations: list[dict[str, Any]],
    route_sequences: dict[str, list[list[str]]],
    stop_lookup: dict[str, Stop],
) -> None:
    for rec in recommendations:
        if rec["action"] != "reallocate_flex_bus":
            continue
        seq = donor_regular_sequence(rec, route_sequences, stop_lookup)
        if len(seq) < 2:
            continue
        pull_time = parse_dt(rec["pull_point"]["available_at"])
        if rec["pull_point"]["type"] == "route_end":
            times = route_stop_times_ending_at(seq, pull_time, stop_lookup)
        else:
            times = route_stop_times(seq, pull_time - timedelta(minutes=20), stop_lookup)
        rec["donor_regular_trip"] = {
            "route_id": rec["from_route_id"],
            "trip_id": f"{rec['bus_id']}_REGULAR_{slug(rec['from_route_id'], 8)}_BEFORE_PULL",
            "stops": seq,
            "depart": times[0].isoformat(timespec="seconds"),
            "arrive": times[-1].isoformat(timespec="seconds"),
        }


def write_csv_to_zip(zf: zipfile.ZipFile, name: str, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    zf.writestr(name, buf.getvalue())


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def append_row(fieldnames: list[str], rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    rows.append({field: row.get(field, "") for field in fieldnames})


def ensure_field(fieldnames: list[str], field: str) -> None:
    if field not in fieldnames:
        fieldnames.append(field)


def flex_label_for_destination(stop_name: str) -> str:
    norm = normalise_name(stop_name)
    if "jahn" in norm:
        return "5"
    if "hauptbahnhof" in norm or norm == "hbf":
        return "5"
    return "5"


def relief_route_id_for_mission(rec: dict[str, Any], route_ids: set[str]) -> str:
    """Passenger-facing route for the relief trip.

    For the Jahn demo, line 5 is the visible support route. If the base feed ever
    lacks route 5, fall back to the donor route rather than inventing a new one.
    """
    return "5" if "5" in route_ids else rec["from_route_id"]


def manifest_for_recommendations(
    recommendations: list[dict[str, Any]],
    service_day: date,
    relief_trip_ids: dict[str, str],
    reposition_trip_ids: dict[str, str],
) -> dict[str, Any]:
    vehicles: list[dict[str, Any]] = []
    for rec in recommendations:
        if rec["action"] != "reallocate_flex_bus":
            continue
        donor = rec.get("donor_regular_trip", {})
        vehicles.append(
            {
                "vehicle_id": rec["bus_id"],
                "block_id": rec["bus_id"],
                "recommendation_id": rec["recommendation_id"],
                "score": rec["score"],
                "explanation": rec["explanation"],
                "segments": [
                    {
                        "type": "service",
                        "role": "regular_before_pull",
                        "route_id": rec["from_route_id"],
                        "trip_id": donor.get("trip_id"),
                        "from_stop": donor.get("stops", [None])[0],
                        "to_stop": donor.get("stops", [None])[-1],
                        "depart": donor.get("depart"),
                        "arrive": donor.get("arrive"),
                    },
                    {
                        "type": "reposition",
                        "role": "terminal_to_relief_origin",
                        "route_id": OUT_OF_SERVICE_ROUTE_ID,
                        "trip_id": reposition_trip_ids.get(rec["recommendation_id"]),
                        "from_stop": rec["deadhead"]["from_stop"],
                        "to_stop": rec["deadhead"]["to_stop"],
                        "depart": rec["deadhead"]["depart"],
                        "arrive": rec["deadhead"]["arrive"],
                        "duration_min": rec["deadhead"]["duration_min"],
                    },
                    {
                        "type": "service",
                        "role": "flex_relief",
                        "route_id": rec["new_flex_route"]["route_id"],
                        "trip_id": relief_trip_ids[rec["recommendation_id"]],
                        "from_stop": rec["new_flex_route"]["stops"][0],
                        "to_stop": rec["new_flex_route"]["stops"][-1],
                        "desired_depart": rec["new_flex_route"]["desired_depart"],
                        "depart": rec["new_flex_route"]["depart"],
                        "arrive": rec["new_flex_route"]["arrive"],
                    },
                ],
            }
        )
    return {
        "service_date": service_day.isoformat(),
        "description": "Flex-bus scenario sidecar. GTFS service trips use public routes; unboardable repositioning uses the single OUT_OF_SERVICE operational route.",
        "vehicles": vehicles,
    }


def gtfs_time(ts: datetime, service_day: date) -> str:
    delta = ts - datetime.combine(service_day, datetime.min.time())
    seconds = int(delta.total_seconds())
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def generate_gtfs_zip(
    recommendations: list[dict[str, Any]],
    stop_lookup: dict[str, Stop],
    out_zip: Path,
) -> dict[str, Any]:
    active = [r for r in recommendations if r["action"] == "reallocate_flex_bus"]
    if not active:
        raise SystemExit("no active reallocations to write to GTFS")

    service_day = parse_dt(active[0]["new_flex_route"]["depart"]).date()
    stop_names = sorted(
        {
            stop
            for rec in active
            for stop in (
                rec["deadhead"]["from_stop"],
                rec["deadhead"]["to_stop"],
                *rec["new_flex_route"]["stops"],
                *rec.get("donor_regular_trip", {}).get("stops", []),
            )
        }
    )

    if not (RAW_GTFS / "routes.txt").exists():
        raise SystemExit(f"base GTFS missing in {RAW_GTFS}; expected routes.txt, trips.txt, stop_times.txt, ...")

    agency_fields, agency_rows = read_csv_rows(RAW_GTFS / "agency.txt")
    stops_fields, stops_rows = read_csv_rows(RAW_GTFS / "stops.txt")
    routes_fields, routes_rows = read_csv_rows(RAW_GTFS / "routes.txt")
    trips_fields, trips_rows = read_csv_rows(RAW_GTFS / "trips.txt")
    stop_times_fields, stop_times_rows = read_csv_rows(RAW_GTFS / "stop_times.txt")
    calendar_fields, calendar_rows = read_csv_rows(RAW_GTFS / "calendar.txt")
    calendar_dates_fields, calendar_dates_rows = read_csv_rows(RAW_GTFS / "calendar_dates.txt")

    for field in ("agency_id", "agency_name", "agency_url", "agency_timezone"):
        ensure_field(agency_fields, field)
    if not any(r.get("agency_id") == SERVICE_AGENCY_ID for r in agency_rows):
        append_row(
            agency_fields,
            agency_rows,
            {
                "agency_id": SERVICE_AGENCY_ID,
                "agency_name": "Omnibus Flex Scenario",
                "agency_url": "https://example.local/omnibus",
                "agency_timezone": "Europe/Berlin",
            },
        )

    existing_stop_ids = {row.get("stop_id", "") for row in stops_rows}
    for name in stop_names:
        stop = stop_lookup[name]
        if stop.stop_id in existing_stop_ids:
            continue
        append_row(
            stops_fields,
            stops_rows,
            {
                "stop_id": stop.stop_id,
                "stop_code": stop.stop_code,
                "stop_name": stop.stop_name,
                "stop_lat": stop.stop_lat,
                "stop_lon": stop.stop_lon,
                "location_type": 0,
                "wheelchair_boarding": 0,
            },
        )
        existing_stop_ids.add(stop.stop_id)

    base_route_ids = {row.get("route_id", "") for row in routes_rows}
    relief_trip_ids: dict[str, str] = {}
    reposition_trip_ids: dict[str, str] = {}

    if OUT_OF_SERVICE_ROUTE_ID not in base_route_ids:
        append_row(
            routes_fields,
            routes_rows,
            {
                "route_id": OUT_OF_SERVICE_ROUTE_ID,
                "agency_id": SERVICE_AGENCY_ID,
                "route_short_name": OUT_OF_SERVICE_ROUTE_SHORT_NAME,
                "route_long_name": "Out of service / unboardable repositioning",
                "route_type": 3,
                "route_desc": "Operational movement. Passengers cannot board this vehicle segment.",
                "route_color": "666666",
                "route_text_color": "FFFFFF",
            },
        )
        base_route_ids.add(OUT_OF_SERVICE_ROUTE_ID)

    for rec in active:
        route_id = relief_route_id_for_mission(rec, base_route_ids)
        rec["new_flex_route"]["route_id"] = route_id

        donor_trip = rec.get("donor_regular_trip")
        if donor_trip:
            append_row(
                trips_fields,
                trips_rows,
                {
                    "route_id": donor_trip["route_id"],
                    "service_id": "SCENARIO_SERVICE",
                    "trip_id": donor_trip["trip_id"],
                    "trip_headsign": donor_trip["stops"][-1],
                    "direction_id": "",
                    "block_id": rec["bus_id"],
                    "shape_id": "",
                },
            )
            donor_times = route_stop_times_ending_at(
                donor_trip["stops"],
                parse_dt(donor_trip["arrive"]),
                stop_lookup,
            )
            for seq, (stop_name, ts) in enumerate(zip(donor_trip["stops"], donor_times), start=1):
                append_row(
                    stop_times_fields,
                    stop_times_rows,
                    {
                        "trip_id": donor_trip["trip_id"],
                        "arrival_time": gtfs_time(ts, service_day),
                        "departure_time": gtfs_time(ts, service_day),
                        "stop_id": stop_lookup[stop_name].stop_id,
                        "stop_sequence": seq,
                        "pickup_type": 0,
                        "drop_off_type": 0,
                    },
                )

        reposition_stops = [rec["deadhead"]["from_stop"], rec["deadhead"]["to_stop"]]
        if reposition_stops[0] != reposition_stops[1]:
            reposition_trip_id = f"{rec['bus_id']}_OUT_OF_SERVICE_{slug(rec['recommendation_id'], 20)}"
            reposition_trip_ids[rec["recommendation_id"]] = reposition_trip_id
            append_row(
                trips_fields,
                trips_rows,
                {
                    "route_id": OUT_OF_SERVICE_ROUTE_ID,
                    "service_id": "SCENARIO_SERVICE",
                    "trip_id": reposition_trip_id,
                    "trip_headsign": "Out of service",
                    "trip_short_name": "unboardable",
                    "direction_id": "",
                    "block_id": rec["bus_id"],
                    "shape_id": "",
                },
            )
            start = parse_dt(rec["deadhead"]["depart"])
            for seq, (stop_name, ts) in enumerate(
                zip(reposition_stops, route_stop_times(reposition_stops, start, stop_lookup)), start=1
            ):
                append_row(
                    stop_times_fields,
                    stop_times_rows,
                    {
                        "trip_id": reposition_trip_id,
                        "arrival_time": gtfs_time(ts, service_day),
                        "departure_time": gtfs_time(ts, service_day),
                        "stop_id": stop_lookup[stop_name].stop_id,
                        "stop_sequence": seq,
                        "pickup_type": 1,
                        "drop_off_type": 1,
                    },
                )

        flex_trip_id = f"{rec['bus_id']}_RELIEF_ROUTE_{slug(route_id, 12)}_{parse_dt(rec['new_flex_route']['depart']):%H%M}"
        relief_trip_ids[rec["recommendation_id"]] = flex_trip_id
        append_row(
            trips_fields,
            trips_rows,
            {
                "route_id": route_id,
                "service_id": "SCENARIO_SERVICE",
                "trip_id": flex_trip_id,
                "trip_headsign": rec["new_flex_route"]["stops"][-1],
                "trip_short_name": f"{rec['bus_id']} flex relief",
                "block_id": rec["bus_id"],
            }
        )
        flex_start = parse_dt(rec["new_flex_route"]["depart"])
        times = route_stop_times(rec["new_flex_route"]["stops"], flex_start, stop_lookup)
        for seq, (stop_name, ts) in enumerate(zip(rec["new_flex_route"]["stops"], times), start=1):
            append_row(
                stop_times_fields,
                stop_times_rows,
                {
                    "trip_id": flex_trip_id,
                    "arrival_time": gtfs_time(ts, service_day),
                    "departure_time": gtfs_time(ts, service_day),
                    "stop_id": stop_lookup[stop_name].stop_id,
                    "stop_sequence": seq,
                    "pickup_type": 0,
                    "drop_off_type": 0,
                }
            )

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        write_csv_to_zip(zf, "agency.txt", agency_fields, agency_rows)
        write_csv_to_zip(zf, "stops.txt", stops_fields, stops_rows)
        write_csv_to_zip(zf, "routes.txt", routes_fields, routes_rows)
        write_csv_to_zip(zf, "trips.txt", trips_fields, trips_rows)
        write_csv_to_zip(zf, "stop_times.txt", stop_times_fields, stop_times_rows)
        service_date = service_day.strftime("%Y%m%d")
        append_row(
            calendar_fields,
            calendar_rows,
            {
                "service_id": "SCENARIO_SERVICE",
                "monday": 1,
                "tuesday": 1,
                "wednesday": 1,
                "thursday": 1,
                "friday": 1,
                "saturday": 1,
                "sunday": 1,
                "start_date": service_date,
                "end_date": service_date,
            },
        )
        append_row(
            calendar_dates_fields,
            calendar_dates_rows,
            {"service_id": "SCENARIO_SERVICE", "date": service_date, "exception_type": 1},
        )
        write_csv_to_zip(zf, "calendar.txt", calendar_fields, calendar_rows)
        write_csv_to_zip(zf, "calendar_dates.txt", calendar_dates_fields, calendar_dates_rows)

        handled = {
            "agency.txt", "stops.txt", "routes.txt", "trips.txt",
            "stop_times.txt", "calendar.txt", "calendar_dates.txt",
            "regensburg_stops.parquet",
        }
        for path in RAW_GTFS.iterdir():
            if path.is_file() and path.name not in handled:
                zf.write(path, arcname=path.name)

    return manifest_for_recommendations(active, service_day, relief_trip_ids, reposition_trip_ids)


def json_default(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat(timespec="seconds")
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"{type(obj)!r} is not JSON serializable")


def run_engine(pressure_path: Path | None, scenario_id: str, force: bool) -> Path:
    out_dir = OUT_ROOT / scenario_id
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise SystemExit(f"{out_dir} already exists. Use --force to overwrite outputs.")
    out_dir.mkdir(parents=True, exist_ok=True)

    stops = load_stop_lookup()
    route_sequences = load_route_sequences()
    pressures = load_pressures(pressure_path, stops)
    service_day = min(p.time_bucket for p in pressures).date()
    route_pressure = route_pressure_by_line(route_sequences, pressures)
    missions = build_missions(pressures, stops)
    donors, rejected = build_donor_candidates(MOCK_FLEET, route_pressure, service_day)
    recommendations = allocate(missions, donors, stops)
    enrich_recommendations_with_donor_trips(recommendations, route_sequences, stops)

    payload = {
        "scenario_id": scenario_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "engine_version": "flex-recommend-v1",
        "route_pressure_by_line": route_pressure,
        "route_constraints": ROUTE_CONSTRAINTS,
        "rejected_donor_candidates": rejected,
        "recommendations": recommendations,
    }
    (out_dir / "recommendations.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )
    (out_dir / "pressure_input.json").write_text(
        json.dumps([asdict(p) for p in pressures], indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )
    (out_dir / "fleet_snapshot.json").write_text(
        json.dumps(MOCK_FLEET, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    scenario_manifest = generate_gtfs_zip(recommendations, stops, out_dir / "scenario_gtfs.zip")
    (out_dir / "scenario_manifest.json").write_text(
        json.dumps(scenario_manifest, indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )
    return out_dir


def main() -> None:
    global RAW_GTFS
    ap = argparse.ArgumentParser(description="Generate flex-bus recommendations and scenario GTFS.")
    ap.add_argument("--pressure-json", type=Path, help="Directional pressure JSON from the pressure model.")
    ap.add_argument("--scenario-id", default="jahn_match_demo", help="Output scenario id under data/scenarios/.")
    ap.add_argument("--force", action="store_true", help="Overwrite existing scenario outputs.")
    ap.add_argument(
        "--gtfs-dir",
        type=Path,
        default=RAW_GTFS,
        help="Base GTFS feed directory to overlay the scenario onto (default: data/raw/gtfs).",
    )
    args = ap.parse_args()

    RAW_GTFS = args.gtfs_dir

    out_dir = run_engine(args.pressure_json, args.scenario_id, args.force)
    print(f"[ok] wrote {out_dir / 'recommendations.json'}")
    print(f"[ok] wrote {out_dir / 'scenario_gtfs.zip'}")


if __name__ == "__main__":
    main()
