"""Response models for the demand API — mirror the artifacts in
analysis/docs/DEMAND_BUCKET_SCHEMA.md. Dummy stubs for now; the frontend can also
read the static demand_<date>.json / demand_<date>_events.json files directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Leg(BaseModel):
    # board stop_code. "from" is a Python keyword, so the field is from_ and we
    # alias it on the wire (both read + write) so the JSON / OpenAPI key is "from".
    from_: str = Field(alias="from", serialization_alias="from")
    to: str | None  # destination stop_code (inbound -> venue, outbound -> origin)
    start: str  # pressure ramps up, "HH:MM"
    end: str  # pressure dies out, "HH:MM"
    peak_s: float  # absolute peak (boarding-dwell seconds)
    pressure_s: list[float]  # absolute curve, one value per tick
    pressure_norm: list[float]  # same curve normalized 0-1 vs peak_s

    model_config = {"populate_by_name": True}


class EventCurves(BaseModel):
    event_id: str
    label: str
    type: str
    venue: str
    event_start: str  # kickoff, "HH:MM"
    event_end: str  # whistle, "HH:MM"
    stops: list[str]  # every stop with a curve (map highlight)
    legs: list[Leg]


class EventsResponse(BaseModel):
    """Shape of demand_<date>_events.json."""

    date: str
    resolution_min: int
    events: list[EventCurves]


# --- demand surface (demand_<date>.json) ----------------------------------
# Mirrors analysis/docs/DEMAND_BUCKET_SCHEMA.md. Every series array has length
# n_ticks, index = tick, aligned to tick_times.


class NodeEvent(BaseModel):
    """One event's contribution to a single stop's event_s series."""

    event_id: str
    event_label: str
    leg: str  # "inbound" | "outbound" | "onsite"
    to: str | None  # destination stop_code this pressure flows to (null if onsite)
    multiplier: float
    active_ticks: list[int]
    contribution_s: list[float]  # this event's share of event_s, length n_ticks


class DemandNode(BaseModel):
    stop_code: str
    lat: float
    lon: float
    pressure_s: list[float]  # absolute boarding-dwell seconds, length n_ticks
    pressure_norm: list[float]  # 0-1 vs the day's global max (heatmap weight)
    baseline_s: list[float]  # event-free baseline, length n_ticks
    event_s: list[float]  # sum of event bumps, length n_ticks
    events: list[NodeEvent]  # events touching this stop; [] if none


class DemandSurface(BaseModel):
    """Shape of demand_<date>.json — the node-keyed 15-min pressure surface."""

    date: str
    resolution_min: int
    n_ticks: int
    tick_times: list[str]  # index -> "HH:MM" window start, length n_ticks
    nodes: list[DemandNode]


# --- bus trajectories (trajectories_<date>.json) --------------------------
# Produced by analysis/pipeline/sumo/*. One SUMO-simulated vehicle per trip,
# sampled in geo coords. Drives the animated bus layer on the same sim clock.


class FlexSegment(BaseModel):
    """One leg of a flex block, for painting the bus per-leg on the map."""

    role: str  # "service" (line-10 leg) | "reposition" (unboardable) | "relief"
    line: str  # leg's GTFS line ("10", "OUT", "5")
    start: int  # seconds since midnight this leg begins (matches points' t)


class BusTrajectory(BaseModel):
    id: str  # gtfs2pt vehicle id (unique per trip)
    line: str  # GTFS line short name ("1", "3", "5", "10", "X4")
    # Scripted flex blocks only: block id ("FLEX_10_02") + flag. A flex bus is a
    # line-10 vehicle that pulls off, deadheads, then runs a route-5 relief leg.
    block: str | None = None
    flex: bool = False
    # flex blocks only: per-leg identity (10 → OUT → 5) with the second each leg
    # starts, so the UI can distinguish the unboardable reposition from service.
    segments: list[FlexSegment] | None = None
    # each point is [t_seconds_since_midnight, lon, lat, angle_deg]
    points: list[list[float]]


class Trajectories(BaseModel):
    """Shape of trajectories_<date>.json — SUMO bus replay for the demo window."""

    date: str
    begin: int  # first sampled second-of-day
    end: int  # last sampled second-of-day
    buses: list[BusTrajectory]
