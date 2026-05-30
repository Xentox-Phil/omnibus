import os
from pathlib import Path

# Demand artifacts produced by analysis/pipeline/predict_demand.py.
DEMAND_DIR = Path(os.environ.get("DEMAND_DIR", "../analysis/data/demand"))
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
).split(",")
# Any localhost port (the Vite dev server hops to 3001+ if 3000 is taken).
CORS_ORIGIN_REGEX = os.environ.get(
    "CORS_ORIGIN_REGEX", r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
)
