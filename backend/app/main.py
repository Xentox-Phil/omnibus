"""Omnibus demand API — DUMMY STUB.

Serves the demand artifacts produced by analysis/pipeline/predict_demand.py.
For now these are static files the frontend could also fetch directly; this thin
layer exists so we have a typed endpoint to grow into. No Valhalla, no routing.

Run:  uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGIN_REGEX, CORS_ORIGINS, DEMAND_DIR
from app.models import DemandSurface, EventsResponse

app = FastAPI(title="Omnibus demand API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _load(name: str) -> dict:
    path = DEMAND_DIR / name
    if not path.exists():
        raise HTTPException(404, f"{name} not found — run predict_demand.py --date <d>")
    return json.loads(path.read_text())


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/demand/{date}", response_model=DemandSurface, operation_id="getDemand")
def demand_surface(date: str) -> dict:
    """The node-keyed 15-min pressure surface (demand_<date>.json)."""
    return _load(f"demand_{date}.json")


@app.get("/events/{date}", response_model=EventsResponse, operation_id="getEvents")
def event_curves(date: str) -> dict:
    """The event-first 1-min curve export (demand_<date>_events.json)."""
    return _load(f"demand_{date}_events.json")
