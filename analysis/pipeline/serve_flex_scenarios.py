"""Tiny read-only HTTP server for generated flex-bus scenarios.

Run from analysis/:
    uv run python pipeline/serve_flex_scenarios.py --port 8090

Endpoints:
    GET /api/scenarios
    GET /api/scenarios/<scenario_id>/recommendations.json
    GET /api/scenarios/<scenario_id>/gtfs.zip
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

SCENARIOS = Path("data/scenarios")


def safe_scenario_id(value: str) -> str:
    if not value or "/" in value or "\\" in value or value.startswith("."):
        raise ValueError("invalid scenario id")
    return value


class ScenarioHandler(BaseHTTPRequestHandler):
    server_version = "OmnibusFlexScenarioServer/1.0"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: object) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - stdlib API name
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]

        try:
            if parts == ["api", "scenarios"]:
                scenarios = []
                if SCENARIOS.exists():
                    for path in sorted(p for p in SCENARIOS.iterdir() if p.is_dir()):
                        scenarios.append(
                            {
                                "scenario_id": path.name,
                                "recommendations_url": f"/api/scenarios/{path.name}/recommendations.json",
                                "gtfs_url": f"/api/scenarios/{path.name}/gtfs.zip",
                            }
                        )
                self._json(200, {"scenarios": scenarios})
                return

            if len(parts) == 4 and parts[:2] == ["api", "scenarios"]:
                scenario_id = safe_scenario_id(parts[2])
                scenario_dir = SCENARIOS / scenario_id
                if parts[3] == "recommendations.json":
                    path = scenario_dir / "recommendations.json"
                    if not path.exists():
                        self._json(404, {"error": "recommendations not found"})
                        return
                    self._send(200, path.read_bytes(), "application/json")
                    return
                if parts[3] == "gtfs.zip":
                    path = scenario_dir / "scenario_gtfs.zip"
                    if not path.exists():
                        self._json(404, {"error": "gtfs zip not found"})
                        return
                    self._send(200, path.read_bytes(), "application/zip")
                    return

            self._json(404, {"error": "not found"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[server] {self.address_string()} - {fmt % args}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve generated flex scenario outputs.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ScenarioHandler)
    print(f"[serve] http://{args.host}:{args.port}/api/scenarios")
    server.serve_forever()


if __name__ == "__main__":
    main()
