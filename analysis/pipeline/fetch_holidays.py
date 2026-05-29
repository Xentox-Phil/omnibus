"""Fetch Bavarian public + school holidays from Open-Holidays-API -> Parquet.

Source: openholidaysapi.org (EU-funded, no key). Country=DE, Subdivision=DE-BY.
Multi-day school holiday ranges are expanded to one row per calendar date.

Output schema:
    date       Date
    kind       String   "public" | "school"
    name       String   German name (e.g. "Tag der Arbeit", "Herbstferien")
    nationwide Boolean  true for federal holidays, false for Bavaria-only

Usage:
    .venv/bin/python pipeline/fetch_holidays.py
    .venv/bin/python pipeline/fetch_holidays.py --force
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import polars as pl

OUT = Path("data/parquet/holidays_bavaria.parquet")
BASE = "https://openholidaysapi.org"
COUNTRY = "DE"
SUBDIVISION = "DE-BY"
LANG = "DE"


def fetch_endpoint(endpoint: str, start: dt.date, end: dt.date) -> list[dict]:
    params = {
        "countryIsoCode": COUNTRY,
        "languageIsoCode": LANG,
        "validFrom": start.isoformat(),
        "validTo": end.isoformat(),
        "subdivisionCode": SUBDIVISION,
    }
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json"}
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            print(f"  attempt {attempt + 1} failed: {e}; retrying...")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Open-Holidays fetch ({endpoint}) failed: {last}")


def pick_name(entry: dict) -> str:
    names = entry.get("name") or []
    # Prefer German, fall back to any.
    for n in names:
        if n.get("language") == LANG:
            return n.get("text", "")
    return names[0].get("text", "") if names else ""


def expand(entry: dict, kind: str) -> list[dict]:
    start = dt.date.fromisoformat(entry["startDate"])
    end = dt.date.fromisoformat(entry["endDate"])
    name = pick_name(entry)
    nationwide = bool(entry.get("nationwide", False))
    days = (end - start).days + 1
    return [
        {
            "date": start + dt.timedelta(days=i),
            "kind": kind,
            "name": name,
            "nationwide": nationwide,
        }
        for i in range(days)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f"{OUT} exists ({OUT.stat().st_size / 1e3:.1f} kB) — skip. Use --force to refetch.")
        return

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)

    # API rejects ranges > ~1 year with HTTP 400; page per calendar year.
    def fetch_yearly(endpoint: str) -> list[dict]:
        out: list[dict] = []
        for year in range(start.year, end.year + 1):
            y_start = max(start, dt.date(year, 1, 1))
            y_end = min(end, dt.date(year, 12, 31))
            out.extend(fetch_endpoint(endpoint, y_start, y_end))
        return out

    print(f"fetching Bavarian public holidays {start} -> {end}...")
    public = fetch_yearly("PublicHolidays")
    print(f"  {len(public)} entries")

    print(f"fetching Bavarian school holidays {start} -> {end}...")
    school = fetch_yearly("SchoolHolidays")
    print(f"  {len(school)} entries (will be expanded to per-day rows)")

    rows: list[dict] = []
    for e in public:
        rows.extend(expand(e, "public"))
    for e in school:
        rows.extend(expand(e, "school"))

    df = pl.DataFrame(rows).sort(["date", "kind", "name"]).unique(maintain_order=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT, compression="zstd")
    print(f"  {df.height:,} day-rows -> {OUT} ({OUT.stat().st_size / 1e3:.1f} kB)")


if __name__ == "__main__":
    main()
