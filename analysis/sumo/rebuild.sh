#!/usr/bin/env bash
# Rebuild the whole scenario from inputs, then refresh the viewer data.
# Usage:
#   bash rebuild.sh [DATE] [BEGIN] [END]
# Examples:
#   bash rebuild.sh                      # defaults: 20250728, 07:00-08:00
#   bash rebuild.sh 20250729 0 86400     # full day
#
# Requires: this folder's pyproject.toml (uv resolves SUMO automatically),
# plus gtfs.zip and regensburg.net.xml present in this folder.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
export PATH="$HOME/.local/bin:$PATH"

DATE="${1:-20250728}"
BEGIN="${2:-25200}"
END="${3:-28800}"

export SUMO_HOME="$(uv run python -c 'import os,sumo;print(os.path.dirname(sumo.__file__))')"
echo "SUMO_HOME=$SUMO_HOME  DATE=$DATE  window=$BEGIN..$END"

# (optional) rebuild network from OSM — only if regensburg_bbox.osm.xml exists
if [ -f regensburg_bbox.osm.xml ] && [ ! -f regensburg.net.xml ]; then
  echo ">> netconvert: OSM -> regensburg.net.xml"
  uv run netconvert --osm-files regensburg_bbox.osm.xml -o regensburg.net.xml
fi

echo ">> gtfs2pt: GTFS -> routes/stops/vtypes (date $DATE)"
uv run python "$SUMO_HOME/tools/import/gtfs/gtfs2pt.py" \
    --gtfs gtfs.zip --date "$DATE" --modes bus \
    --network regensburg.net.xml \
    --route-output gtfs_pt_vehicles.add.xml \
    --additional-output gtfs_pt_stops.add.xml \
    --vtype-output pt_vtypes.xml

echo ">> patch time window in regensburg.sumocfg ($BEGIN..$END)"
# portable in-place edit (works on macOS + Linux)
python3 - "$BEGIN" "$END" <<'PY'
import re, sys
b, e = sys.argv[1], sys.argv[2]
s = open("regensburg.sumocfg").read()
s = re.sub(r'(<begin value=")[^"]*(")', rf'\g<1>{b}\g<2>', s)
s = re.sub(r'(<end value=")[^"]*(")',   rf'\g<1>{e}\g<2>', s)
open("regensburg.sumocfg", "w").write(s)
PY

echo ">> sumo: run headless with geo FCD"
uv run sumo -c regensburg.sumocfg --fcd-output sim.fcd.xml --fcd-output.geo true

echo ">> convert FCD -> viewer_data.json"
uv run python fcd_to_json.py sim.fcd.xml viewer_data.json 3

echo ">> (optional) regenerate sample demand.json"
uv run python generate_demand.py || echo "   (skipped demand: needs gtfs.zip)"

echo "DONE. Now: bash serve_viewer.sh  ->  http://localhost:8000/viewer.html"
