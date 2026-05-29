# External Data Sources

Companion to `pipeline/fetch_*.py`. All scripts are **idempotent** — skip if the
output parquet already exists, re-run with `--force` to refetch.

Run order (only `university_calendar` depends on another):

```
.venv/bin/python pipeline/fetch_weather.py
.venv/bin/python pipeline/fetch_holidays.py
.venv/bin/python pipeline/fetch_university_calendar.py   # needs holidays parquet
```

---

## 1. Weather — Open-Meteo Historical

**Source:** https://archive-api.open-meteo.com/v1/archive — free, no API key.
**Location:** Regensburg, `lat=49.013, lng=12.101`.
**Tz:** Europe/Berlin.

**Output:** `data/parquet/weather_regensburg.parquet` (~340 kB, 29k hourly rows
covering 2023-01-01 → ~2 days before today; archive lags ~2 days).

Columns: `ts` (datetime, Europe/Berlin), `temp_c`, `precip_mm`, `wind_kmh`,
`wind_gust_kmh`, `visibility_m`, `weather_code` (WMO), `humidity_pct`,
`cloud_cover_pct`, `snowfall_cm`.

**Quirks:**
- API returns local-time strings *including* the skipped spring-forward hour
  and the duplicated fall-back hour. Fetcher uses
  `dt.replace_time_zone(TZ, non_existent="null", ambiguous="earliest")` then
  drops the null row.
- Fallback if Open-Meteo dies: DWD station 03379.

### 1b. Daylight — Open-Meteo (same call)

`fetch_weather.py` adds `daily=sunrise,sunset,daylight_duration` to the same API
roundtrip and writes a second parquet:

**Output:** `data/parquet/daylight_regensburg.parquet` (~24 kB, 1,243 daily rows).

Columns: `date` (Date), `sunrise` and `sunset` (datetime, Europe/Berlin —
DST-aware, CET↔CEST automatic), `daylight_hours` (Float64, derived from
`daylight_duration / 3600`).

Sanity-checked: 21 Jun 2024 → 16.2 h daylight (sunrise 05:07, sunset 21:19);
21 Dec 2024 → 8.2 h (sunrise 09:03, sunset 17:16); CET↔CEST flips on the
correct Sundays.

Use it to mark trips as `is_night = ts >= sunset OR ts <= sunrise` and
to separate evening-darkness ridership patterns from daytime ones.

---

## 2. Bavarian Holidays — Open-Holidays-API

**Source:** https://openholidaysapi.org — free, no key, EU-funded.
- `GET /PublicHolidays?countryIsoCode=DE&subdivisionCode=DE-BY&languageIsoCode=DE&validFrom=…&validTo=…`
- `GET /SchoolHolidays?…` (same params)

**Output:** `data/parquet/holidays_bavaria.parquet` (~3.5 kB, 442 day-rows
covering 2023-01-01 → 2026-12-31).

Columns: `date`, `kind` ∈ {`public`, `school`}, `name` (German), `nationwide`
(true for federal holidays, false for Bavaria-only).

**Quirks:**
- API rejects ranges > ~1 year with HTTP 400. Fetcher pages per calendar year.
- Multi-day school holiday ranges (e.g. Herbstferien) are expanded to one row
  per calendar day on write — joins are simpler.
- A single date may have both a `public` and a `school` row (e.g. Fronleichnam
  during Pfingstferien). Dedup if you don't want this.

---

## 3. University Calendars — OTH Regensburg + Uni Regensburg

**Output:** `data/parquet/university_calendar.parquet` (~5.7 kB, 1,441 day-rows
covering 2023-03 → 2026-07 across both institutions).

Columns: `date`, `institution` ∈ {`oth`, `ur`}, `in_session` (bool — true on
weekdays inside Vorlesungszeit that are neither a Bavarian public holiday nor
explicitly flagged lecture-free), `note` (short reason: `vorlesungstag`,
`wochenende`, `feiertag:Tag der Arbeit`, `vorlesungsfrei:weihnachten`, etc.).

### OTH (auto-fetched ICS, where available)

Files live at:

```
https://www.oth-regensburg.de/fileadmin/Bereiche/Organisation/Termine_und_Oeffnungszeiten/
```

Two naming conventions exist in parallel; OTH switched mid-2024:

| Pattern                                            | Used for         |
| -------------------------------------------------- | ---------------- |
| `{SoSe|WiSe}_{YYYY}_Terminplan_Studierende.ics`    | older semesters  |
| `{SoSe|WiSe}{YYYY}_-_Terminplan_Studierende.ics`   | newer semesters  |

Not every semester is online — older files get removed and brand-new ones
appear shortly before the semester starts. As of 2026-05-29, ICS available for:
**SoSe 2023, WiSe 2023/24, WiSe 2024/25, WiSe 2025/26, SoSe 2026**.

Raw ICS files are cached under `data/raw/oth_ics/` (re-used across runs).

ICS parser looks for these event SUMMARY markers:
- `↑ Beginn Lehrveranstaltungen` → semester start (DTSTART = first lecture day)
- `Ende aller Lehrveranstaltungen` → semester end (DTSTART = last lecture day)
- `Keine Lehrveranstaltung; …` → explicit lecture-free single day

### OTH (manual fallback for missing ICS)

Hardcoded in the `MANUAL` table in `pipeline/fetch_university_calendar.py`:

| Semester       | Vorlesungszeit          | Verified?           | Source                                                                                                            |
| -------------- | ----------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------- |
| OTH SoSe 2024  | 2024-03-18 → 2024-07-05 | ⚠ best-effort       | `SoSe_2024_Semesterkalender.pdf` exists at OTH `fileadmin/Bereiche/Organisation/Termine_und_Oeffnungszeiten/` but was not parsed; dates match typical OTH SoSe pattern |
| OTH SoSe 2025  | 2025-03-17 → 2025-07-11 | ⚠ best-effort       | `SoSe_2025_Semesterkalender.pdf`, same source; dates match typical OTH SoSe pattern                               |

### Uni Regensburg (manual — no ICS published)

UR only publishes PDFs (`uni-regensburg.de/assets/studium/studium/semesterkalender-tabelle-{sose|wise}{YYYY}.pdf`).
Boundaries hardcoded in `MANUAL`:

| Semester        | Vorlesungszeit          | Verified?    | Source                                                                                                          |
| --------------- | ----------------------- | ------------ | --------------------------------------------------------------------------------------------------------------- |
| UR SoSe 2023    | 2023-04-17 → 2023-07-21 | ⚠ pattern    | Bavarian university standard (mid-Apr → late-Jul); no direct citation                                            |
| UR WiSe 2023/24 | 2023-10-16 → 2024-02-09 | ⚠ pattern    | Bavarian university standard; consistent with OTH WiSe_2023 ICS framing                                          |
| UR SoSe 2024    | 2024-04-15 → 2024-07-19 | ⚠ pattern    | Bavarian university standard                                                                                     |
| UR WiSe 2024/25 | 2024-10-14 → 2025-02-07 | ⚠ pattern    | Bavarian university standard                                                                                     |
| UR SoSe 2025    | 2025-04-23 → 2025-07-25 | ✓ confirmed  | UR Semesterkalender page (https://www.uni-regensburg.de/studieren/im-studium/studienorganisation/semesterkalender) — note Tue 22.04.2025 vorlesungsfrei (day after Easter), Vorlesungen begin Wed 23.04.2025 |
| UR WiSe 2025/26 | 2025-10-13 → 2026-02-06 | ⚠ partial    | end date 05.02 / 06.02.2026 reported on UR Semesterkalender; start date inferred from Bavarian standard          |

**"⚠ pattern" rows have NOT been verified against the official PDF.** If you
need exact boundaries (e.g. for a year-over-year compare against the OTH ICS
truth), parse the UR PDF and update `MANUAL` in `pipeline/fetch_university_calendar.py`.

### Christmas-break heuristic

The OTH ICS only explicitly marks the Brückentag (e.g. 23.12) as lecture-free
— the rest of the Christmas vacation (24.12 onwards) is **implicit** under
§ 1 Abs. 4 of OTH's Satzung über die Vorlesungszeit, so it's missing from the
ICS feed. To fix this, the parser hardcodes:

> **Dec 24 through Jan 6 (inclusive) are always vorlesungsfrei** for any
> in-progress semester at any German university.

Tagged `note = "vorlesungsfrei:weihnachten"`.

### Verification

- UR SoSe 2025: first in_session = 2025-04-23, last = 2025-07-25, 64 lecture
  days. Matches the official UR calendar exactly.
- Tag der Arbeit (2025-05-01, Thursday): correctly `feiertag:Tag der Arbeit`
  for both institutions.
- 2024-12-24 Heiligabend: correctly `vorlesungsfrei:weihnachten`.

### Known caveats

- Hardcoded UR/OTH-gap dates are **best-effort** from public sources. If an
  analyst hits a date that disagrees with the published calendar, edit
  `MANUAL` in `pipeline/fetch_university_calendar.py` and rerun with `--force`.
- Pfingstferien at UR is school-style; the script doesn't include it as a
  bulk lecture-free range. If you need it, add a `extra_free` entry to the
  relevant `ManualSemester`.
- This is a *Vorlesungszeit* table, not a class-attendance table. "In session"
  means "lectures are scheduled", not "every student is on a bus."
- We do **not** have per-class timetables (LSF / SPLAN data). If you need a
  "class just ended" signal, derive it empirically: stack dwell time at
  university stops across all `in_session=true` days and look for the 90-min
  Bavarian lecture-slot rhythm (Akademisches Viertel: ~09:45, 11:30, 13:15, ...).

---

---

## 4. Regensburg Events (manual CSV)

Per-row-sourced CSV at `data/raw/events_regensburg_2024_2025.csv` → parquet
sibling via `pipeline/ingest_external_csvs.py`.

**Output:** `data/parquet/events_regensburg.parquet` (~11 kB, 345 day-rows
covering 2024–2026).

Columns: `date`, `event_name`, `event_type` ∈ {`sport_football`,
`sport_icehockey`, `festival_folk`, `festival_christmas`, `festival_city`,
`marathon`, `concert`, `other`}, `venue`, `expected_demand_window` (e.g.
`kickoff_18:30`, `all_day`), `approx_attendance` (Int64, nullable),
`source_url`, `source_title`, `confidence` ∈ {`high`, `medium`, `low`},
`notes`.

Methodology + full source list + known gaps (esp. Eisbären 2024/25 schedule
incomplete) in [`EVENTS.md`](./EVENTS.md).

---

## 5. RVV-relevant Strikes (manual CSV)

Per-row-sourced CSV at `data/raw/strikes_rvv_2024_2025.csv` → parquet sibling.

**Output:** `data/parquet/strikes_rvv.parquet` (~6 kB, 3 day-rows).

Columns: `date`, `duration` ∈ {`full_day`, `partial`, `warning_strike`,
`unknown`}, `scope` ∈ {`national`, `bayern`, `regensburg_local`,
`rvv_specific`}, `affected_service`, `description`, `source_url`,
`source_title`, `confidence`, `notes`.

**Headline null finding:** zero ver.di bus-driver strikes hit RVV / das
Stadtwerk.Mobilität in 2024 or 2025. Bayern was in **Friedenspflicht** during
both the Feb/Mar 2024 nationwide ÖPNV Warnstreik wave and the 21 Feb 2025
ÖPNV strike — Bayern explicitly excluded from both. First Stadtbus strike in
this dispute cycle was 2 Feb 2026, outside the analysis window. The 3 rows
included are TVöD/TV-V Stadtwerke strikes (REWAG, Kitas, MedBO) where bus
drivers were not on the call list — kept for completeness with
`affected_service=unknown`. Full methodology in [`STRIKES.md`](./STRIKES.md).

Implication for analysis: **any 2024/2025 Line 1 anomaly is not strike-caused.**

---

## Sources

- Open-Meteo Historical API — https://open-meteo.com/en/docs/historical-weather-api
- Open-Holidays-API — https://openholidaysapi.org/swagger/index.html
- OTH Regensburg — Termine und Öffnungszeiten — https://www.oth-regensburg.de/die-oth/termine-und-oeffnungszeiten
- OTH Regensburg ICS directory — https://www.oth-regensburg.de/fileadmin/Bereiche/Organisation/Termine_und_Oeffnungszeiten/
- Uni Regensburg — Semesterkalender — https://www.uni-regensburg.de/studieren/im-studium/studienorganisation/semesterkalender
- Universität Bayern e.V. — Vorlesungszeiten — https://www.unibayern.de/vorlesungszeiten
