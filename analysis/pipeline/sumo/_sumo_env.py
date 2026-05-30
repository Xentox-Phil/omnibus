"""Shared SUMO environment setup.

The `eclipse-sumo` wheel ships the binaries (sumo, netconvert, duarouter) and the
`tools/` scripts (osmGet.py, import/gtfs/gtfs2pt.py) but does NOT export SUMO_HOME.
The tool scripts and typemaps rely on it, so we point it at the installed package
and make `$SUMO_HOME/tools` importable. Import this module before using any tool.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def sumo_home() -> Path:
    import sumo  # provided by the eclipse-sumo wheel

    return Path(sumo.__file__).resolve().parent


def setup() -> Path:
    """Set SUMO_HOME, add tools/ to sys.path, return the SUMO_HOME path."""
    home = sumo_home()
    os.environ.setdefault("SUMO_HOME", str(home))
    tools = home / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    return home


def tool(rel: str) -> str:
    """Absolute path to a tool script under $SUMO_HOME/tools, e.g. 'osmGet.py'."""
    p = sumo_home() / "tools" / rel
    if not p.exists():
        raise FileNotFoundError(f"SUMO tool not found: {p}")
    return str(p)


def binary(name: str) -> str:
    """Absolute path to a SUMO binary (sumo, netconvert, ...)."""
    setup()
    from sumolib import checkBinary

    return checkBinary(name)


# Canonical scenario paths (all under analysis/data/sumo/, gitignored + regenerable).
REPO_ANALYSIS = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ANALYSIS / "data" / "sumo"
GTFS_JULY = REPO_ANALYSIS / "data" / "raw" / "gtfs_july2025"
