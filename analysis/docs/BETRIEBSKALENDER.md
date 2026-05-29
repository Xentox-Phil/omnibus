# SMO Betriebskalender 2023 / 2024 / 2025

das.Stadtwerk.Mobilität (SMO) publishes a one-page year-overview "Betriebskalender" (operations calendar) that overlays operationally-relevant annotations on a standard kalenderpedia-style year grid. Three issues are in the raw dataset:

- `data/raw/2023_SMO_Betriebskalender.pdf`
- `data/raw/2024_SMO_Betriebskalender.pdf`
- `data/raw/2025 - SMO-Betriebskalender.pdf`

All three are **text-based PDFs** (not scanned images) — readable directly, no OCR needed.

## What's on the page

Each cell carries: day-of-month, weekday abbrev (Mo–So), and (for Mondays) the ISO week number. Background color + small label encodes operational context. The legend at the bottom maps colors to:

| Legend marker            | Meaning                                                                                            |
| ------------------------ | -------------------------------------------------------------------------------------------------- |
| **UNI** color            | Day inside Uni Regensburg lecture period (Vorlesungszeit)                                          |
| **OTH** color            | Day inside OTH Regensburg lecture period                                                           |
| **V-Frei**               | Lecture-free single day *inside* an otherwise active Vorlesungszeit (long weekend, etc.)           |
| **DULT**                 | Dult festival window (Mai-Dult / Herbst-Dult) — operational uplift                                 |
| **Einstellung EMIL \| Altstadtbus ab 13:00** | EMIL (free downtown circulator) and Altstadtbus shut down at 13:00      |
| **Verstärkung Berufsschulen (X1)** | Single weekday in early-/mid-September where the vocational schools restart and SMO adds reinforcement runs |
| **Marathon**             | Regensburg Marathon route closures                                                                 |
| **Bürgerfest**           | City festival, dense Altstadt closures                                                             |
| **Samstagsfahrplan Heiligabend und Silvester** *(2025 onward)* | Both days run Saturday timetable regardless of weekday |
| **Modul // voraussichtlicher Termin** | Planned operational module event — date sometimes tentative ("?")                          |
| **Beginn / Ende Eislauf Linie D** | Start/end of seasonal ice-rink shuttle (Donau-Arena), Linie D                              |
| **FP-Wechsel**           | Fahrplanwechsel — timetable change effective date                                                  |

## What's unique to the Betriebskalender (not in our other parquets)

Most public holidays are already in `holidays_bavaria.parquet`. Marathon, Dult, and Bürgerfest dates are in `events_regensburg.parquet`. Uni/OTH lecture periods are in `university_calendar.parquet`.

**Operationally-distinct annotations only the Betriebskalender carries:**

1. **FP-Wechsel** (Fahrplanwechsel) — explicit timetable change dates. Only 2025 marks one (2025-01-20). 2023's footer notes "Kleine Anpassungen im Dez und ggf. nach den Osterferien — **nicht markiert**", so unmarked minor adjustments exist in all years.
2. **X1 Berufsschulen Verstärkung** — extra capacity in week 37/38 when vocational schools restart. One Monday per year.
3. **EMIL & Altstadtbus 13:00 cutoff** on Heiligabend / Silvester — pattern documented in legend for all 3 years.
4. **Samstagsfahrplan on weekday Heiligabend/Silvester** — only made explicit in 2025 legend (Dec 24 + Dec 31 2025 fall on Wednesdays). Implied for 2024 Tue 24./31. Dec. Irrelevant in 2023 (both fell on Sunday).
5. **Eislauf Linie D** seasonal ice-rink shuttle — explicit start/end dates. Only 2024 has both endpoints labeled in text (Beginn 2024-09-21, Ende 2024-03-31). 2025 calendar has the legend slot but no extracted Beginn date in the text layer.
6. **Modul // voraussichtlicher Termin** — a planned operational module rollout. 2023 has a tentative one on Mon 2023-10-02 marked with "?". 2024 and 2025 calendar cells don't carry an explicit date in the text layer (only the legend example).
7. **V-Frei within lecture period** — short lecture-free interruptions that don't show up in the OTH/UR ICS feeds, e.g. 2023-04-11 (post-Osterferien), 2023-05-30 (after Pfingsten), 2024-05-21 (post-Pfingsten), 2025-07-10. Useful demand-side signal.

## Quirks observed across years

- **Typo in 2023 footer:** "Herbst 25.08.-10.09.22" — 2022 is wrong, should be 2023 (the Herbst-Dult dates align with our `events_regensburg.parquet` entry for 2023).
- **Landesturnfest 28.04 – 01.05.2023** is the only one-off mega-event listed in 2023 and not repeated in 2024/2025.
- **P+R Shuttle 2023:** legend shows "bis jetzt kein Angebot" (no offering yet). A P+R label exists in the legend but wasn't operated.
- **Reformationstag (Oct 31)** is annotated each year but is **not** a public holiday in Bavaria — likely a UI artifact of the kalenderpedia template; do not treat as service-impacting.
- **Faschingsdienstag (Feb 13)** explicitly marked in 2024 only. Rosenmontag is marked in all three.
- **2025 has no "?"-marked tentative dates** — calendar appears more finalized than 2023's.

## Structured extraction

Day-resolution structured extract → [`data/raw/betriebskalender_events.csv`](../data/raw/betriebskalender_events.csv).

Schema:

| column          | type | notes                                                                                          |
| --------------- | ---- | ---------------------------------------------------------------------------------------------- |
| `date`          | date | ISO date                                                                                       |
| `dow`           | str  | Mo/Di/Mi/Do/Fr/Sa/So                                                                           |
| `iso_week`      | int  | ISO week, 1–52/53                                                                              |
| `category`      | str  | see categories below                                                                           |
| `event_name`    | str  | German label as it appears in the PDF                                                          |
| `notes`         | str  | extra context (e.g. "EMIL/Altstadtbus stop at 13:00")                                          |
| `source_year`   | int  | which Betriebskalender it came from (2023/2024/2025) — same date can appear from two issues    |

Categories: `holiday_public`, `holiday_religious`, `holiday_observance`, `carnival`, `fahrplanwechsel`, `reinforcement_x1`, `modul`, `marathon`, `festival_buergerfest`, `festival_dult`, `festival_other`, `v_frei`, `eislauf_start`, `eislauf_end`, `sommerzeit_start`, `sommerzeit_end`, `service_reduction`, `service_samstagsfahrplan`.

Bürgerfest and Dult are recorded as start + end rows only (not every day in between) since the date span is the operational fact.

## Why this matters for Omnibus

Per `BRIEF.md` the model needs context for atypical operational days. The Betriebskalender provides three signals not derivable from RVV telemetry alone:

1. **Demand-side modifiers** (V-Frei days inside lecture periods; X1 day before vocational schools start; Eislauf-Linie-D active months) → useful for the dwell-time→demand inference (Person 2 / Model B).
2. **Supply-side modifiers** (FP-Wechsel dates → bus runs may legitimately differ from "expected schedule"; EMIL/Altstadtbus 13:00 cutoff → don't flag the afternoon absence as a malfunction).
3. **Service-pattern overrides** (Samstagsfahrplan on weekday Heiligabend/Silvester → a Tuesday running on Saturday frequencies is *correct*, not a defect).

If we treat any of those days as "normal weekday" the residuals will be junk.
