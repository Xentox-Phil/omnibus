# Omnibus — RVV transit data pipeline

Hackaburg 2026. Public-transit optimization for RVV (Regensburg).
Project context & conventions: [`CLAUDE.md`](./CLAUDE.md) · challenge: [`BRIEF.md`](./BRIEF.md).

## Setup

We use **[uv](https://docs.astral.sh/uv/)** — Astral's Rust-based Python package manager. Why:

- ⚡ 10–100× faster than pip/poetry (matters when teammates clone fresh during the hackathon)
- 🔒 `uv.lock` pins exact versions → reproducible installs across all machines
- 🐍 Auto-downloads the right Python version (no "wrong Python" debugging)
- 🚀 One command (`uv sync`) replaces `python -m venv` + `activate` + `pip install`
- 📦 Standard `pyproject.toml` — no lock-in, anyone can fall back to plain pip if they want

Install uv once:

```bash
brew install uv                                                    # macOS
winget install --id=astral-sh.uv -e                                # Windows
curl -LsSf https://astral.sh/uv/install.sh | sh                    # Linux
```

Then from inside `analysis/`:

```bash
uv sync     # creates .venv, installs deps from pyproject.toml + uv.lock
```

That's it — no manual venv activation needed. `uv run <cmd>` runs anything
inside the project venv automatically.

### How it works

- **`pyproject.toml`** — declares deps (polars, pyarrow) and Python version (`>=3.11`). This is the standard Python project manifest (PEP 621). Edit it to add a dep, then `uv sync`.
- **`uv.lock`** — auto-generated, commits exact resolved versions of every transitive dep. Don't edit by hand; uv rewrites it on `uv sync` / `uv add`.
- **`.venv/`** — local virtual environment uv creates on first `uv sync`. Gitignored.
- **`uv run python pipeline/foo.py`** — runs the script with the project venv, no activation needed. Works identically on macOS, Windows, Linux.

Common commands:

```bash
uv add pandas              # add a dependency (updates pyproject.toml + uv.lock)
uv remove pandas           # remove one
uv sync                    # install/update deps to match the lockfile
uv sync --upgrade          # bump deps within pyproject.toml constraints
uv run python -c "..."     # run anything inside the project venv
```

## Onboarding

**No data is committed** — `data/raw/` and `data/parquet/` are gitignored (binary
blobs would drown the repo). After cloning you have an empty `data/` skeleton.
Get the raw RVV bundle from a teammate, drop it into the paths in
[`data/README.md`](./data/README.md), then build the parquet:

```bash
uv sync                              # one-time: install deps
uv run python pipeline/run.py        # build the whole pipeline (smart-cached)
```

`run.py` is the **conductor**: it runs every stage in dependency order, skips
any whose parquet already exists, soft-skips RVV ingest if you don't have the
raw bundle yet (the external fetchers still run), and prints a summary. Flags:

```bash
uv run python pipeline/run.py --force                  # rebuild everything
uv run python pipeline/run.py --only assemble          # one stage (+ use --force to rebuild)
uv run python pipeline/run.py --skip ingest            # everything except ingest
```

`assemble.py` is the **final stage of `run.py`, not a separate step you run
after it.** `run.py` already calls it last (once its inputs exist), joining every
source into one analysis-ready table at stop-event grain →
`data/parquet/features.parquet` (weather, daylight, holidays, university sessions,
events, strikes as context columns). Read it with:

```python
import polars as pl
df = pl.read_parquet("data/parquet/features.parquet")   # the modelling table
```

**What depends on what is *data*, not scripts.** `assemble` needs the RVV window
parquets + the six context parquets to already be on disk — it doesn't care
*how* they got there. So you have two equivalent ways to build `features.parquet`:

- **`uv run python pipeline/run.py`** — runs the whole chain incl. assemble. Use
  this from a fresh clone, or any time you're not sure what's stale; already-built
  stages are skipped, so it's cheap to re-run.
- **`uv run python pipeline/assemble.py`** — runs *only* the join, against whatever
  parquets are already in `data/parquet/`. Use this when the upstream parquets
  exist and you just want to (re)build the features table.

You never run `run.py` *and then* `assemble.py` — pick one. Likewise any single
stage runs standalone (`uv run python pipeline/fetch_weather.py`) when you only
want to refresh one source; afterwards rebuild the table with
`uv run python pipeline/assemble.py --force`.

## The features table (`features.parquet`)

The modelling table. One row per **stop-event** (trip × stop), built by
`pipeline/assemble.py` — it concatenates all six RVV stop-event parquets into one
base, then LEFT-joins the external context so no row multiplies:

| Context | Joined on | Adds |
| --- | --- | --- |
| weather | local wall-clock hour of arrival | `temp_c`, `precip_mm`, `wind_kmh`, `weather_code`, `humidity_pct`, `cloud_cover_pct`, `snowfall_cm`, … |
| daylight | `operating_day` | `sunrise_ts`, `sunset_ts`, `daylight_hours` |
| holidays | `operating_day` | `is_public_holiday`, `is_school_holiday`, `holiday_name` |
| university | `operating_day` | `oth_in_session`, `ur_in_session` |
| events | `operating_day` | `has_event`, `event_count`, `event_attendance_sum/max`, `event_names`, `event_types` |
| strikes | `operating_day` | `strike_any`, `strike_scope` |

Boolean flags (`has_event`, `is_*_holiday`, `strike_any`) are filled `False` on
days with no match, so they're never null.

### Generate it

```bash
uv run python pipeline/run.py                          # as part of the full pipeline
uv run python pipeline/assemble.py                     # just this stage (skips if it exists)
uv run python pipeline/assemble.py --force             # rebuild from current parquets
```

`assemble` reads whatever RVV + context parquets are present in `data/parquet/`,
so run the upstream stages (or the conductor) first.

### Which dataset is which — the `source_window` column

Every row carries `source_window` = the original RVV parquet it came from. Filter
on it to isolate a window:

```python
import polars as pl
df = pl.read_parquet("data/parquet/features.parquet")

flood   = df.filter(pl.col("source_window") == "26.05.2024_07.06.2024_ITCS_Hochwasser")
line1   = df.filter(pl.col("source_window") == "Daten_Linie_1_2024-09_2025-08")
xmas    = df.filter(pl.col("source_window").str.starts_with("15.12.2024"))   # Christkindlmarkt
windows = df.filter(pl.col("source_window") != "Daten_Linie_1_2024-09_2025-08")  # event windows only
```

| `source_window` | what | dates |
| --- | --- | --- |
| `08.10.2023_21.10.2023_ITCS` | baseline autumn | 2023-10-08 → 10-21 |
| `26.05.2024_07.06.2024_ITCS_Hochwasser` | flood | 2024-05-26 → 06-07 |
| `Daten_Linie_1_2024-09_2025-08` | Line 1 full year | 2024-09-01 → 2025-08-31 |
| `06.10.2024_19.10.2024_ITCS` | baseline autumn | 2024-10-06 → 10-19 |
| `15.12.2024_25.12.2024_ITCS_Christkindlmarkt2024` | Christmas market | 2024-12-15 → 12-25 |
| `23.04.2025_09.05.2025_ITCS_nur_UniLinien` | uni lines only | 2025-04-23 → 05-09 |

> **Overlap caveat:** the event windows fall *inside* the Line-1 full year, so a
> given date can appear under **two** `source_window` values. Always slice on
> `source_window`, not on date, to keep windows separate (or filter out
> `Daten_Linie_1_2024-09_2025-08` first to dedupe).

## Scripts (`pipeline/`)

| Script | What it does | Input | Output |
| --- | --- | --- | --- |
| `ingest.py` | RVV ITCS CSVs → tidy parquet | `data/raw/rvv/*` | `data/parquet/<window>.parquet` |
| `ingest_external_csvs.py` | Manually-researched events + strikes CSVs → typed parquet | `data/raw/{events_regensburg,strikes_rvv}_*.csv` | `events_regensburg.parquet`, `strikes_rvv.parquet` |
| `fetch_weather.py` | Hourly weather (Open-Meteo) | — (API) | `weather_regensburg.parquet` |
| `fetch_holidays.py` | Bavaria public + school holidays | — (API) | `holidays_bavaria.parquet` |
| `fetch_university_calendar.py` | OTH/UR term calendars | API + holidays parquet | `university_calendar.parquet` |

```bash
uv run python pipeline/fetch_weather.py             # --force to refetch
uv run python pipeline/fetch_holidays.py
uv run python pipeline/fetch_university_calendar.py # needs holidays parquet first
uv run python pipeline/ingest.py                    # --file <name> for one file
uv run python pipeline/ingest_external_csvs.py      # events + strikes CSVs → parquet
```

Fetchers are idempotent (skip if output exists; `--force` to refetch).

## Raw RVV data (not in git)

Not redistributable → gitignored. Ask a teammate for the bundle and place files
exactly per [`data/README.md`](./data/README.md) before running `ingest.py`.
