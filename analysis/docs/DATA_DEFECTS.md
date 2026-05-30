# Data Defects & Fixes — RVV ITCS Ingest

Log of every defect found in the raw RVV ITCS exports while building
`pipeline/ingest.py`, and how each was handled. Source files live in
`data/raw/rvv/` (gitignored); outputs land in `data/parquet/`.

Severity legend: 🔴 breaks parsing · 🟡 corrupts values silently · 🟢 analysis-time caveat (parser is faithful).

---

## 1. 🔴 UTF-16 encoding

**Defect.** Files are UTF-16 encoded. Plain `open()` / default `read_csv`
yields garbage (null bytes between characters, mangled umlauts).

**Fix.** Read every file with `encoding="utf-16"`.

```python
pl.read_csv(path, encoding="utf-16", ...)
```

---

## 2. 🔴 Two incompatible export formats

The dataset ships in **two different shapes**:

| Format | Files | Layout |
| ------ | ----- | ------ |
| **Wide** | the 5 event CSVs (baseline, YoY, Christmas, Uni, flood) | 25 columns, one row per stop event, the 4 metrics inline as columns 21–24 |
| **Melted (long)** | the `Daten Linie 1/` monthly CSVs | one row **per (stop event, metric)** — the metric *name* in the 2nd-to-last column, its *value* in the last |

**Defect.** A single parser assuming the wide layout crashes on the melted
files (`ShapeError: 25 column names provided for a DataFrame of width 23`).

**Fix.** Two code paths. Melted files are read header-first, then **pivoted**
back to the wide layout (`pivot(values="_value", on="_metric", index=identity)`)
so both formats produce one identical schema downstream.

The 4 metric labels map to canonical columns (whitespace collapsed first — see §6):

| Metric label (German) | Column |
| --------------------- | ------ |
| `Fahrplan-Abw. Abfahrt (Tür) AVG {s}` | `delay_dep_avg_s` |
| `Fahrplan-Abw. Ankunft (Tür) AVG {s}` | `delay_arr_avg_s` |
| `CUMSUM(Distanz PLAN) {m}` | `distance_cum_m` |
| `CUMSUM(Fahrzeit IST) {s}` | `runtime_cum_s` |

---

## 3. 🔴 Empty / duplicated header columns (sub-values)

**Defect.** The header has **blank column names** at positions 10, 12, 14, 17,
19. Each blank column carries a *sub-value* of the named column before it
(e.g. `Haltestelle` = `"HBF"` code, the following blank = `"Hauptbahnhof"`
long name). Polars auto-renames blanks to `''`, `_duplicated_0`, … which are
meaningless. Dropping them blindly would lose the human-readable stop/line names.

**Fix.** Assign all 25 columns by **position** with an explicit name list, splitting
each German column into its code + sub-value:

| Idx | German | Canonical |
| --- | ------ | --------- |
| 9 / 10 | Fahrtbeginn (Soll-Haltestelle) | `trip_start_code` / `trip_start_name` |
| 11 / 12 | Fahrtende (Soll-Haltestelle) | `trip_end_code` / `trip_end_name` |
| 13 / 14 | Haltestelle | `stop_code` / `stop_name` |
| 15 | Haltepunkt | `stop_point` |
| 16 / 17 | Linie | `line_id` / `line` |
| 18 / 19 | Richtung | `direction` / `direction_label` |

> Note: column 16 (`line_id`) is an **internal id** (e.g. `401`, `902`); column 17
> (`line`) is the **public-facing label** (`"C2"`, `"N5"`, `"4A"`). Use `line` for
> anything user-visible.

---

## 4. 🔴 Inconsistent columns across melted monthly files

**Defect.** The 12 Line-1 monthly CSVs do **not** share a column set:

- **Oct 2024** omits the `Haltepunkt` column entirely.
- **Apr 2025** omits `Haltestelle` (and its name sub-column).
- The rest have the full identity set.

Because the metric name/value are always the *last two* fields, a missing
*middle* column shifts every column after it. Symptom: blind positional
parsing produced **4× the expected row count** (140k→564k for Oct, 127k→508k
for Apr) because the pivot index columns were misaligned and nothing collapsed.

(Also: Polars infers a different width per file — 21, 22 or 23 — since it drops
trailing all-empty columns based on the data window, so a fixed positional
schema can't be trusted either.)

**Fix.** **Header-driven** parsing for melted files (`resolve_melted_header`):
read the raw header, map each German label to its canonical name, attach blank
columns as the preceding column's sub-value, and treat the final two trailing
blanks as `_metric` / `_value`. Missing identity columns are added back as
nulls so every month yields the same schema before concatenation.

**Residual + recovery.** Stop identity was null for the two affected months:

| Column | Null rows | Cause | Status |
| ------ | --------- | ----- | ------ |
| `stop_code`, `stop_name` | 126,984 | Apr 2025 lacked `Haltestelle` | ✅ **recovered** |
| `stop_point` | 140,981 | Oct 2024 lacked `Haltepunkt` | ⚠️ not recoverable |

**Apr 2025 (`stop_code`/`stop_name`) — fixed in ingest.** `reconcile_stop_identity()`
(`ingest.py`, called inside `_build_melted` once all 12 months are concatenated)
recovers both: `stop_point` is `"<stop_code> (<position>)"` (e.g. `"HBF (51)"`),
so stripping the trailing `" (NN)"` yields the `stop_code` exactly (verified 100%,
0 mismatches), and a `stop_code → stop_name` lookup built from the months that
carry both fills the name. All 126,984 rows recovered, 0 residual. Self-contained
and reproducible — no external file. This lifted GTFS coordinate coverage of
*all* stop-events from 96.48% → **99.80%** (see [`GTFS.md`](./GTFS.md)).

**Oct 2024 (`stop_point`) — left null.** A `stop_code` maps to *many* `stop_point`s
(one per position), so the position number can't be uniquely recovered from
`stop_code`. `stop_point` isn't needed for geocoding (that keys on `stop_code`),
so these 140,981 nulls are accepted.

---

## 5. 🟡 Numbers use `.` as a *thousands* separator

**Defect.** Numeric fields are German-formatted: `"-1.499"` means **−1499**, not
−1.499. `"11.573"` metres = **11573 m**. A naive `cast(Float)` silently produces
values off by 1000×.

**Fix.** Strip `.` then cast to `Int64`; blank → null.

```python
pl.col(c).str.replace_all(".", "", literal=True).replace("", None).cast(pl.Int64, strict=False)
```

Applies to `delay_dep_avg_s`, `delay_arr_avg_s`, `distance_cum_m`, `runtime_cum_s`.
(No genuine decimals observed — all four are integer seconds/metres.)

---

## 6. 🟡 Inconsistent whitespace in metric labels

**Defect.** The melted metric labels have erratic spacing, e.g.
`"Fahrplan-Abw. Abfahrt (Tür) AVG  {s}"` (double space) vs the single-space
arrival variant. Exact-string lookup against the metric map silently misses,
leaving the value unmapped.

**Fix.** Collapse runs of whitespace before lookup:
`str.replace_all(r"\s+", " ").str.strip_chars()`. The metric map keys use the
normalized single-space form.

---

## 7. 🟢 Timestamps need explicit German format

**Defect.** Timestamps are `"%d.%m.%Y %H:%M:%S"` (`"06.10.2024 05:42:59"`),
`Betriebstag` is `"%d.%m.%Y"`. Auto-inference can misread day/month.

**Fix.** Parse explicitly with `str.to_datetime(fmt, strict=False)` /
`str.to_date(...)`. `strict=False` so the midnight-wrap rows (§9) become null
rather than aborting the parse.

---

## 8. 🟢 Boolean flags are German strings

**Defect.** `Ankunft produktiv` / `Abfahrt produktiv` are `"Ja"` / `"Nein"`.

**Fix.** Cast to real booleans: `(pl.col(c) == "Ja")`.

---

## 9. 🟢 `delay_arr_s` midnight-wrap outliers

**Defect.** Derived `delay_arr_s` (`actual_door − planned`) shows extreme
outliers down to **−51,443 s (≈ −14 h)**. Cause: the `Betriebstag` service day
can exceed 24 h and span past midnight (documented in CLAUDE.md), so a planned
time near `23:5x` paired with an actual just after midnight produces a ~−24 h
delta.

**Fix at ingest:** none — the parser stays faithful to the source. **Flagged
for the analysis layer:** filter implausible deltas (e.g. `|delay| > 2 h`) or
reconstruct the true delta across the day boundary before computing Scene-B
variance.

---

## 10. 🟢 `door_opened` is not a reliable door-open flag

**Defect.** Derived `door_opened = ts_arrival_actual_door is not null` reads
**~100 %** in the wide files, because those exports populate the door timestamp
even on closed-door pass-throughs (door ts == halt ts). So the field does not
actually distinguish doors-open from doors-closed there.

**Fix at ingest:** kept as specified in CLAUDE.md (null-based). **Flagged for
analysis:** to detect a genuine closed-door pass, compare
`ts_arrival_actual_door` vs `ts_arrival_actual_halt` (equal ⇒ doors likely
never opened) rather than trusting `door_opened` alone.

---

## 11. 🔴 No trip identifier (reconstructed)

**Defect.** The data has **no `trip_id`**. Rows are individual stop events; a
"trip" (one vehicle running origin→destination once) is implicit. Without it,
Scene A (consecutive-stop delay diffs) and Scene B (per-trip variance) cannot
group correctly. First guess — `distance_cum_m == 0` marks trip starts — was
wrong: it appears 27k× and misfires (see below).

**Two traps found while reconstructing:**

1. **Departure time is non-monotonic within a trip.** At an origin terminal the
   scheduled *departure* is *later* than the next stop's (layover), so ordering
   rows by `ts_departure_planned` scatters a trip's rows and interleaves them
   with neighbours → tuples flip-flop → catastrophic over-split (50k "trips",
   median 1 stop). Fix: order by **`ts_arrival_planned`** (the bus reaches its
   origin first, so arrival *is* monotonic within a trip).
2. **Planned times are minute-coarse**, so many stops tie. The tie-break must be
   **`distance_cum_m` descending**, so a trip's final stop (high distance) sorts
   *before* the next trip's origin (distance 0). Ascending tie-break re-creates
   the interleaving.

**Fix (`add_trip_id`).** Within each `(operating_day, vehicle_block)`:
sort by `ts_arrival_planned ASC, distance_cum_m DESC`; start a new trip whenever
the identity tuple `(line, direction, trip_start_code, trip_end_code)` changes;
`trip_id = "{operating_day}_{vehicle_block}_{seq}"`. Added `stop_seq` = rank of
`distance_cum_m` within the trip (reliable within-trip stop order).

**Validation (all files).** Productive trips have a sensible **median 22–28
stops**; spurious single-stop *productive* trips are **2–11 per file**
(≤0.05 %). Remaining one-stop trips are **100 % non-productive** deadhead/depot
moves. ~0.4 % of same-route-twice recurrences in a block stay merged — accepted.

> Earlier "No trip identity" gap from the validation review is now **closed**.

---

## Derived fields added at ingest

| Field | Definition |
| ----- | ---------- |
| `delay_arr_s` | `ts_arrival_actual_door − ts_arrival_planned` (seconds) |
| `delay_dep_s` | `ts_departure_actual_door − ts_departure_planned` |
| `dwell_s` | `ts_departure_actual_door − ts_arrival_actual_door` |
| `door_opened` | `ts_arrival_actual_door is not null` (see §10) |
| `trip_id` | reconstructed per-trip id (see §11) |
| `stop_seq` | within-trip stop order, ranked by `distance_cum_m` (see §11) |

---

## Outputs

| Parquet | Rows | Period | Notes |
| ------- | ---- | ------ | ----- |
| `06.10.2024_19.10.2024_ITCS` | 557,927 | baseline 2024 | |
| `08.10.2023_21.10.2023_ITCS` | 564,153 | baseline 2023 (YoY) | |
| `15.12.2024_25.12.2024_ITCS_Christkindlmarkt2024` | 389,706 | Christmas market | |
| `23.04.2025_09.05.2025_ITCS_nur_UniLinien` | 237,857 | uni lines only | |
| `26.05.2024_07.06.2024_ITCS_Hochwasser` | 509,454 | June 2024 flood | |
| `Daten_Linie_1_2024-09_2025-08` | 1,566,130 | full-year Line 1 | melted→pivoted; see §4 nulls |

1.4 GB raw → 122 MB Parquet (zstd).
