# Regensburg Events 2024-2025 (and tail into 2026)

Companion to `analysis/data/raw/events_regensburg_2024_2025.csv`.

Goal: enumerate major Regensburg events that drive bus passenger demand spikes,
so they can be used as features (or controls) in delay/demand models.

One row per **calendar day** the event is active. Multi-day festivals expand
to one row per day. Single-evening sport fixtures get a single row.

## What's in scope

| Category              | Events covered                                                                   |
| --------------------- | -------------------------------------------------------------------------------- |
| `festival_folk`       | Maidult + Herbstdult (2024, 2025)                                                |
| `festival_christmas`  | Christkindlmarkt Neupfarrplatz, Romantischer Weihnachtsmarkt T&T, Lucrezia-Markt |
| `sport_football`      | SSV Jahn Regensburg home games (2. Bundesliga 24/25 + 3. Liga 25/26)             |
| `sport_icehockey`     | Eisbären Regensburg DEL2 home games                                              |
| `marathon`            | Regensburg Marathon 2024 + 2025 (incl. Saturday Minimarathon)                    |
| `festival_city`       | Bürgerfest 2025 (biennial); Gassenfest 2024 (off-year substitute)                |
| `concert`             | Thurn und Taxis Schlossfestspiele (2024 + 2025)                                  |

## CSV columns

| Column                   | Meaning                                                                                     |
| ------------------------ | ------------------------------------------------------------------------------------------- |
| `date`                   | ISO `YYYY-MM-DD`. Multi-day events: one row per day.                                        |
| `event_name`             | Human-readable, e.g. `Maidult 2024`, `Jahn vs 1. FC Köln`.                                  |
| `event_type`             | Controlled vocab (see table above).                                                         |
| `venue`                  | Free-text venue. Stable per event family.                                                   |
| `expected_demand_window` | When demand is concentrated. `kickoff_HH:MM` for sport; `evening_*`, `all_day` for markets. |
| `approx_attendance`      | Per-day estimate (capacity for sport, festival totals). `"unknown"` if no good source.      |
| `source_url`             | Primary source URL.                                                                         |
| `source_title`           | Page/article title.                                                                         |
| `confidence`             | `high` (primary source, exact date), `medium` (inferred or aggregator), `low` (skipped).    |
| `notes`                  | Optional: opening hours, special days, capacity caveats.                                    |

## Search methodology

For each event family:

1. Google search for "<event> Regensburg <year> Termine/dates" + cross-check.
2. Where possible, fetch primary source: city website (regensburg.de), event
   organiser site (e.g. wm-tut.de, buergerfest-regensburg.de, ssv-jahn.de).
3. For sport fixture lists: prefer fussballdaten.de / sportschau.de / hessenschau
   for full machine-readable schedules. Cross-validate kickoff with kicker.de
   sample fixtures.
4. Down-grade confidence to `medium` when only aggregator sources were
   available; skip entirely (no row) if confidence would be `low`.

## Sources consulted

### Dults

- https://www.regensburg.de/aktuelles/dult
- https://www.regensburg-bayern.de/nuetzliche-infos/aktuelles/archiv/maidult-regensburg-2024.html
- https://www.ganz-muenchen.de/volksfeste/umland/regensburg/herbstdult/2024.html
- https://www.ganz-muenchen.de/volksfeste/umland/regensburg/Maidult.html
- https://www.regensburg.de/rathaus/aemteruebersicht/direktorium-1/db-1-direktorialbereich/presse-und-oeffentlichkeitsarbeit/presseservice/aktuelle-pressemitteilungen/559551/597823/herbstdult-2025-dult-ist-kult.html

### Christmas markets

- https://www.regensburg.de/aktuelles/christkindlmarkt/regensburger-christkindlmarkt-2025
- https://www.regensburg.de/aktuelles/christkindlmarkt/weihnachtsmaerkte
- https://www.nordbayern.de/oberpfalz/regensburg/weihnachtsmarkt-in-regensburg-das-mussen-sie-wissen-1.12284156
- https://www.wm-tut.de/ (Romantischer Weihnachtsmarkt T&T)
- https://lucrezia-markt.de/
- https://www.bayernradar.de/events/lucrezia-markt-regensburg
- https://www.regensburg.de/veranstaltungen/detail/544318 (Lucrezia 2025)

### SSV Jahn

- https://www.fussballdaten.de/vereine/jahn-regensburg/2025/spielplan/ (2024/25)
- https://www.fussballdaten.de/vereine/jahn-regensburg/spielplan/ (2025/26)
- https://www.ssv-jahn.de/aktuelles/detail/dfl-veroeffentlicht-spielplan-fuer-die-zweitliga-saison-2024-25
- https://www.kicker.de/jahn-regensburg/spielplan
- https://www.sportschau.de/live-und-ergebnisse/verein/te1070/jahn-regensburg/spielplan-team

### Eisbären

- https://www.hessenschau.de/sport/ergebnisse-tabellen/eishockey-108~team_id-8940.html (2025/26)
- https://eisbaeren-regensburg.com/ (multiple press releases for 2024/25 individual games)
- https://eisbaeren-regensburg.com/del-2-spielplan-steht-eisbaeren-regensburg-starten-mit-heimderby-gegen-landshut-in-neue-saison
- https://www.del-2.org/clubs/eisbaren-regensburg_38

### Marathon

- https://www.regensburg-marathon.de/
- https://www.regensburger-nachrichten.de/sport-und-freizeit/94131-32-regensburg-marathon-2024-laufen-im-weltkulturerbe
- https://www.medalmonday.de/veranstaltungen/regensburg-marathon/2025
- https://spoferan.com/en/events/regensburg-marathon

### Bürgerfest

- https://www.buergerfest-regensburg.de/
- https://www.regensburg.de/kultur/veranstaltungen-des-kulturreferats/buergerfest-2025
- https://heutetag.com/kalender/buergerfest-regensburg/

### Schlossfestspiele

- https://www.thurnundtaxis.com/experience/palace-festival
- https://www.schlossfestspiele-regensburg.de/programm.html
- https://www.eventim.de/artist/thurn-und-taxis-schlossfestspiele/

## Known gaps & caveats

### Eisbären 2024/25 schedule — incomplete
Aggregator pages (sport.de, eishockey.info, hessenschau) returned the **current
season (2025/26)** when queried for archived 2024/25 data — the season filter
URLs did not work. Only **12 home games** of the ~26 in 2024/25 are in the CSV,
each verified individually against an Eisbären press release. The remaining 14
home games likely exist on dates including Sep 27, Oct 4, Oct 18, Nov 8, Nov 22,
Dec 6 (rough Fri/Sun pattern) but I will not invent them. Action: scrape
del-2.org archive or eisbaeren-regensburg.com tag pages with a real HTTP client
if Eisbären 24/25 modelling becomes important.

### Eisbären 2025/26 — partial
25 home games listed (out of likely 26 for the main round). One missing
matchday — the hessenschau snapshot at fetch time may have been mid-update.

### Jahn 25/26 kickoff times
Kickoff times in CSV come from Fussballdaten and represent the broadcast slot.
The DFB/DFL sometimes re-schedules individual matches up to ~6 weeks before
kickoff; the originally-published slot is what's listed. For day-of-game RVV
planning, re-query the official Jahn fixture page near match day.

### Jahn 24/25 kickoff times (marquee games)
Sources rounded some kickoff times to nominal 2.BL slots (Sa 13:00, So 13:30,
Fr 18:30 etc.). For most matches that's accurate; for marquee games (HSV,
Schalke, Köln, Nürnberg) the DFL frequently moves to evening slots — verify
specific dates if doing fine-grained matching.

### Christmas market opening hours
We model the markets as "active all day on listed dates" but actual demand
peaks ~16:00–21:00 (weekday) and ~14:00–22:00 (weekend). The
`expected_demand_window` column captures opening hours; for modelling, treat
the **evening hours** as the peak.

### Attendance numbers
- Dult: rough total festival attendance from city sources (~100k/day plausible
  on peak Saturdays; lower midweek). Stored as 100000 placeholder — DO NOT
  multiply 100k × 18 days = "1.8M per Maidult".
- Football: ~15000 (Jahnstadion capacity, sold-out approximation) for 2.BL;
  ~10000 for 3.Liga where actual averages are lower.
- Ice hockey: ~4500 (Donau-Arena capacity ~4862).
- Bürgerfest: ~500000 over the weekend (city estimate from past editions).
- Christmas markets, Schlossfestspiele: marked `unknown` — no reliable per-day
  numbers found.

These are **rough order of magnitude** for sanity-checking model spikes, not
ground truth. Do not present these as facts.

### Bürgerfest cadence
The Bürgerfest is biennial (every two years). 2025 is the next edition after
2023. In off-years (2024), the much smaller Gassenfest fills the same June
slot — included as a separate row with `medium` confidence and noted as
smaller scale.

### Schlossfestspiele = ticketed concerts
Demand for the Schlossfestspiele is bounded by ticket capacity in the palace
courtyard (~roughly 1500–3000 per show depending on stage config). It's not a
mass-attendance festival like the Dult, but specific evening busses to the
Stadtamhof / palace area will spike. Marked `unknown` for attendance.

## Maintenance

When updating for a new year:

1. Re-run the searches above with `<year>` substituted.
2. For Jahn / Eisbären: refetch from fussballdaten/hessenschau and replace
   rows. Schedules are typically published in June/July.
3. Verify Christmas market opening date (varies by ~1 day based on calendar
   alignment with Totensonntag).
4. Bürgerfest: only present in odd years.
5. Down-grade confidence and add a `notes` entry if a primary source is
   replaced by an aggregator.

## Joining to ITCS data

```python
import polars as pl

events = pl.read_csv("analysis/data/raw/events_regensburg_2024_2025.csv")
itcs = pl.read_parquet("analysis/data/parquet/itcs.parquet")

# Date-only join: any event happening that operating_day
joined = itcs.join(
    events.with_columns(pl.col("date").str.to_date()),
    left_on=pl.col("ts_departure_planned").dt.date(),
    right_on="date",
    how="left",
)
```

For finer-grained features, combine `event_type` × `expected_demand_window` to
build, e.g., `feat_football_kickoff_within_2h` or
`feat_christmas_market_evening`.
