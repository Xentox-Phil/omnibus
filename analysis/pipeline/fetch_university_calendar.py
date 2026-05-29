"""Build a per-day in_session table for OTH Regensburg + Uni Regensburg -> Parquet.

OTH publishes ICS calendars for some semesters; we fetch and parse them.
For semesters where OTH does not publish ICS, and for all UR semesters
(UR publishes only PDFs), we use a manually-curated fallback table.

Output schema:
    date         Date
    institution  String   "oth" | "ur"
    in_session   Boolean  True on weekdays inside Vorlesungszeit that are
                          neither a Bavarian public holiday nor explicitly
                          flagged "Keine Lehrveranstaltung"
    note         String   short reason ("vorlesungstag", "wochenende",
                          "feiertag:Allerheiligen", "vorlesungsfrei:Weihnachten",
                          "ausserhalb-vorlesungszeit")

Usage:
    .venv/bin/python pipeline/fetch_university_calendar.py
    .venv/bin/python pipeline/fetch_university_calendar.py --force
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

OUT = Path("data/parquet/university_calendar.parquet")
RAW_DIR = Path("data/raw/oth_ics")
HOLIDAYS_PARQUET = Path("data/parquet/holidays_bavaria.parquet")

OTH_BASE = (
    "https://www.oth-regensburg.de/fileadmin/Bereiche/"
    "Organisation/Termine_und_Oeffnungszeiten"
)
# Confirmed-available ICS filenames (probed 2026-05-29).
OTH_ICS_FILES = [
    ("sose_2023", "SoSe_2023_Terminplan_Studierende.ics"),
    ("wise_2023", "WiSe_2023_Terminplan_Studierende.ics"),
    ("wise_2024", "WiSe_2024_Terminplan_Studierende.ics"),
    ("wise_2025", "WiSe2025_-_Terminplan_Studierende.ics"),
    ("sose_2026", "SoSe2026_-_Terminplan_Studierende.ics"),
]

# Manual fallback: (institution, label, start, end, [extra free-day dates])
# OTH SoSe 2024 + SoSe 2025: ICS not published; dates from OTH PDFs.
# UR all semesters: UR publishes only PDFs. Dates from the official
# Semesterkalender pages on uni-regensburg.de.
# Public holidays fall on weekdays inside these ranges — those are handled
# automatically via the Bavarian holidays parquet join.
@dataclass
class ManualSemester:
    institution: str
    label: str
    start: dt.date
    end: dt.date
    extra_free: list[dt.date] = field(default_factory=list)


MANUAL = [
    # --- OTH (gaps where no ICS is published) ---
    ManualSemester("oth", "sose_2024",
                   dt.date(2024, 3, 18), dt.date(2024, 7, 5),
                   extra_free=[
                       dt.date(2024, 5, 31),  # Brückentag nach Fronleichnam (typical)
                   ]),
    ManualSemester("oth", "sose_2025",
                   dt.date(2025, 3, 17), dt.date(2025, 7, 11),
                   extra_free=[
                       dt.date(2025, 6, 20),  # Brückentag nach Fronleichnam (typical)
                   ]),
    # --- UR (no ICS published) ---
    ManualSemester("ur", "sose_2023",
                   dt.date(2023, 4, 17), dt.date(2023, 7, 21)),
    ManualSemester("ur", "wise_2023_24",
                   dt.date(2023, 10, 16), dt.date(2024, 2, 9),
                   extra_free=[dt.date(d.year, d.month, d.day) for d in
                               (dt.date(2023, 12, 23) + dt.timedelta(days=i)
                                for i in range(15))]),  # Weihnachtsferien
    ManualSemester("ur", "sose_2024",
                   dt.date(2024, 4, 15), dt.date(2024, 7, 19)),
    ManualSemester("ur", "wise_2024_25",
                   dt.date(2024, 10, 14), dt.date(2025, 2, 7),
                   extra_free=[dt.date(2024, 12, 23) + dt.timedelta(days=i)
                               for i in range(15)]),
    ManualSemester("ur", "sose_2025",
                   dt.date(2025, 4, 23), dt.date(2025, 7, 25)),  # confirmed
    ManualSemester("ur", "wise_2025_26",
                   dt.date(2025, 10, 13), dt.date(2026, 2, 6),
                   extra_free=[dt.date(2025, 12, 24) + dt.timedelta(days=i)
                               for i in range(14)]),
]


# ---------- ICS fetch + parse ----------

def fetch_oth_ics(force: bool) -> list[Path]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for label, fname in OTH_ICS_FILES:
        local = RAW_DIR / fname
        if local.exists() and not force:
            paths.append(local)
            continue
        url = f"{OTH_BASE}/{fname}"
        print(f"  download {fname}...")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    local.write_bytes(r.read())
                paths.append(local)
                break
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"    attempt {attempt + 1}: {e}")
                time.sleep(2 * (attempt + 1))
        else:
            print(f"    SKIP {fname}: all attempts failed")
    return paths


DATE_RE = re.compile(r"DTSTART(?:;[^:]+)?:(\d{8})")
SUMMARY_RE = re.compile(r"^SUMMARY:(.*)$")


def parse_oth_ics(path: Path) -> tuple[dt.date | None, dt.date | None, list[tuple[dt.date, str]]]:
    """Return (semester_start, semester_end, [(date, summary) of lecture-free days])."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # ICS line-fold: lines starting with space/tab continue the previous line.
    text = re.sub(r"\r?\n[ \t]", "", text)

    sem_start: dt.date | None = None
    sem_end: dt.date | None = None
    free: list[tuple[dt.date, str]] = []

    # Iterate VEVENT blocks.
    for block in text.split("BEGIN:VEVENT")[1:]:
        block = block.split("END:VEVENT", 1)[0]
        m_sum = SUMMARY_RE.search(block, re.MULTILINE) or re.search(r"SUMMARY:(.*)", block)
        m_dt = DATE_RE.search(block)
        if not m_sum or not m_dt:
            continue
        summary = m_sum.group(1).strip()
        try:
            d = dt.datetime.strptime(m_dt.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if "Beginn Lehrveranstaltungen" in summary and sem_start is None:
            sem_start = d
        elif "Ende aller Lehrveranstaltungen" in summary:
            sem_end = d
        elif "Keine Lehrveranstaltung" in summary:
            free.append((d, summary))
    return sem_start, sem_end, free


# ---------- assemble per-day table ----------

def _is_christmas_break(d: dt.date) -> bool:
    """Dec 24 through Jan 6 (inclusive): universal German uni Christmas recess.
    ICS feeds often only mark the surrounding Brückentag explicitly."""
    return (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day <= 6)


def expand_semester(institution: str, start: dt.date, end: dt.date,
                    free_days: set[dt.date], free_label: dict[dt.date, str],
                    public_holidays: dict[dt.date, str]) -> list[dict]:
    rows = []
    d = start
    while d <= end:
        if d.weekday() >= 5:
            note, in_sess = "wochenende", False
        elif d in public_holidays:
            note, in_sess = f"feiertag:{public_holidays[d]}", False
        elif d in free_days:
            note, in_sess = f"vorlesungsfrei:{free_label.get(d, '')}", False
        elif _is_christmas_break(d):
            note, in_sess = "vorlesungsfrei:weihnachten", False
        else:
            note, in_sess = "vorlesungstag", True
        rows.append({"date": d, "institution": institution,
                     "in_session": in_sess, "note": note})
        d += dt.timedelta(days=1)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f"{OUT} exists ({OUT.stat().st_size / 1e3:.1f} kB) — skip. Use --force.")
        return

    if not HOLIDAYS_PARQUET.exists():
        raise SystemExit(
            f"missing {HOLIDAYS_PARQUET}; run pipeline/fetch_holidays.py first"
        )
    holidays = pl.read_parquet(HOLIDAYS_PARQUET).filter(pl.col("kind") == "public")
    public_holidays: dict[dt.date, str] = dict(
        zip(holidays["date"].to_list(), holidays["name"].to_list())
    )

    # Collect (institution, semester_id, start, end, free_days) from ICS + manual.
    semesters: list[tuple[str, str, dt.date, dt.date, dict[dt.date, str]]] = []

    print("fetching OTH ICS files...")
    for ics_path in fetch_oth_ics(args.force):
        label = ics_path.stem.split("_-_")[0] if "_-_" in ics_path.stem else \
                ics_path.stem.replace("_Terminplan_Studierende", "")
        s, e, free = parse_oth_ics(ics_path)
        if not (s and e):
            print(f"  WARN: could not parse start/end from {ics_path.name}")
            continue
        free_map = {d: lbl.split(";")[-1].strip() or "frei" for d, lbl in free}
        semesters.append(("oth", label.lower(), s, e, free_map))
        print(f"  OTH {label}: {s} -> {e}, {len(free_map)} free days")

    print(f"adding {len(MANUAL)} manual-fallback semesters...")
    for m in MANUAL:
        free_map = {d: "manuell" for d in m.extra_free}
        semesters.append((m.institution, m.label, m.start, m.end, free_map))

    rows: list[dict] = []
    seen: set[tuple[str, dt.date]] = set()
    for inst, _label, s, e, free in semesters:
        for r in expand_semester(inst, s, e, set(free.keys()), free, public_holidays):
            key = (inst, r["date"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)

    df = pl.DataFrame(rows).sort(["institution", "date"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT, compression="zstd")
    print(f"  {df.height:,} day-rows -> {OUT} ({OUT.stat().st_size / 1e3:.1f} kB)")

    # Quick summary.
    summary = df.group_by("institution").agg(
        pl.len().alias("days"),
        pl.col("in_session").sum().alias("in_session"),
    ).sort("institution")
    print(summary)


if __name__ == "__main__":
    main()
