#!/usr/bin/env bash
# Serve the browser viewer locally (the browser blocks fetch() over file://).
# Then open http://localhost:8000/viewer.html
#   bash serve_viewer.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PORT="${1:-8000}"
echo "Serving $DIR at http://localhost:$PORT/viewer.html  (Ctrl+C to stop)"
# python3 is enough — no SUMO needed just to view
exec python3 -m http.server "$PORT"
