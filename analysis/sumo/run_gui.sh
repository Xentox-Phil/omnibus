#!/usr/bin/env bash
# Launch the Regensburg SUMO scenario in the GUI. Run from anywhere:
#   bash run_gui.sh        (uses this folder's own pyproject.toml via uv)
set -euo pipefail

# absolute dir of this script (so it works no matter where you call it from)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# make sure uv is reachable even in a fresh terminal
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' not found. Install it or add ~/.local/bin to PATH:"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  exit 1
fi

cd "$DIR"
# resolve SUMO_HOME from the project's venv automatically
export SUMO_HOME="$(uv run python -c 'import os,sumo;print(os.path.dirname(sumo.__file__))')"
echo "SUMO_HOME=$SUMO_HOME"
echo "launching sumo-gui on regensburg.sumocfg ..."
exec uv run sumo-gui -c regensburg.sumocfg
