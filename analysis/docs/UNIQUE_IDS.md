# Deriving Unique IDs for the RVV ITCS Dataset

How we turned a flat stream of stop events into addressable **trips** and
**stops** — what the data does *not* give you, the false trails, and the rule we
landed on. Implemented in [`pipeline/ingest.py`](../pipeline/ingest.py)
(`add_trip_id`); see also [`DATA_DEFECTS.md`](./DATA_DEFECTS.md) §11.

---

## The problem

Each row is **one stop event** — a vehicle arriving/departing one stop at one
time. There is **no `trip_id`, no `vehicle_id`, no run number**. To analyse
reliability (variance over a trip) or infrastructure (delay added between two
consecutive stops) you must first know *which rows belong to the same trip*.

What the dataset *does* give us, per row:

| Column | Use for IDs |
| ------ | ----------- |
| `operating_day` | the service day (can exceed 24 h) |
| `vehicle_block` (`Umlauf`) | one vehicle's depot-to-depot duty — contains **many** trips |
| `line`, `direction` | which route, which way |
| `trip_start_code`, `trip_end_code` | the trip's origin & destination terminals |
| `distance_cum_m` | metres travelled **since the start of the current trip** (resets to 0 each trip) |
| `ts_arrival_planned`, `ts_departure_planned` | schedule times at this stop |

So a **trip** is one run of a single `(line, direction, origin, destination)`
inside one `(operating_day, vehicle_block)`. The job is to detect where one trip
ends and the next begins.

---

## What didn't work (and why)

### ❌ Attempt 1 — "a trip starts where `distance_cum_m == 0`"

Intuitive: the cumulative-distance counter resets to 0 at each origin. But `0`
appears ~27k times and **misfires**: it splits a single row off the front of a
trip whenever that trip's origin row is *out of order* (see Trap A). Produced
4,353 one-stop "trips", 3,269 of them mid-trip fragments.

### ❌ Attempt 2 — "a trip = a run of the same identity tuple, ordered by departure time"

Correct idea (tuple change = boundary), wrong sort key. It **exploded to ~50,000
trips with a median of 1 stop**. Two traps were behind it:

#### Trap A — departure time is *non-monotonic within a trip*

At an origin terminal the scheduled **departure** can be *later* than the next
stop's (the bus sits on a layover, then departs). Ordering a trip's rows by
`ts_departure_planned` therefore puts the origin *after* its own second stop, so
the trip's rows scatter and interleave with the neighbouring trip — the identity
tuple flip-flops and every row looks like a new trip.

> **Fix:** order by **`ts_arrival_planned`**. The bus *reaches* its origin before
> anything else, so arrival time *is* monotonic along a trip.

#### Trap B — planned times are minute-coarse, so rows tie

Many stops share the same planned minute. When timestamps tie, the secondary
sort decides whether same-trip rows stay contiguous. Sorting the tie by
**`distance_cum_m` descending** makes a trip's *last* stop (high distance) sort
*before* the next trip's *origin* (distance 0), keeping each trip's rows together.
Ascending re-creates the interleaving.

---

## ✅ The rule we use

Within each `(operating_day, vehicle_block)`:

1. **Order** rows by `ts_arrival_planned` ascending, breaking ties by
   `distance_cum_m` **descending**.
2. **Start a new trip** whenever the identity tuple
   `(line, direction, trip_start_code, trip_end_code)` differs from the previous
   row.
3. **`trip_id`** = `"{operating_day}_{vehicle_block}_{seq}"` where `seq` is the
   running trip count within the block.
4. **`stop_seq`** = rank of `distance_cum_m` within the trip — the reliable
   within-trip stop order (distance is monotonic where time isn't).

```python
TRIP_TUPLE = ["line", "direction", "trip_start_code", "trip_end_code"]
block = ["operating_day", "vehicle_block"]

df = (
    df.with_columns(
        pl.coalesce("ts_arrival_planned", "ts_departure_planned").alias("_order_ts")
    )
    .sort([*block, "_order_ts", "distance_cum_m"], descending=[False, False, False, True])
)
prev   = pl.struct(TRIP_TUPLE).shift(1).over(block)
is_new = (pl.struct(TRIP_TUPLE) != prev) | prev.is_null()

df = df.with_columns(is_new.cum_sum().over(block).alias("_seq")).with_columns(
    (pl.col("operating_day").cast(str) + "_"
     + pl.col("vehicle_block").fill_null("NA") + "_"
     + pl.col("_seq").cast(str)).alias("trip_id")
).with_columns(
    pl.col("distance_cum_m").rank("ordinal").over("trip_id").alias("stop_seq")
)
```

### Why tuple-change, not the distance reset?

The identity tuple is **constant for every row of a trip** regardless of row
order, so it is immune to Trap A. The distance reset is only a single row and is
fragile to ordering. We rely on the tuple for the boundary and use distance only
for the tie-break and for `stop_seq`.

---

## Resulting keys

| Key | Grain | Definition |
| --- | ----- | ---------- |
| `trip_id` | one vehicle run | `{operating_day}_{vehicle_block}_{seq}` |
| `trip_id` + `stop_seq` | one stop event within a trip | unique per stop on a trip |
| `(line, direction, stop_code, time-bucket)` | aggregate (Scene B) | derived downstream, not stored |

---

## Validation

Run across all six datasets. Productive (passenger-service) trips look right;
artifacts are negligible.

| Dataset | Trips | Productive trips | Median stops | Productive 1-stop artifacts |
| ------- | ----: | ---------------: | -----------: | --------------------------: |
| baseline 2024 | 27,881 | 23,389 | 26 | 7 |
| baseline 2023 | 28,488 | 24,242 | 24 | 9 |
| Christmas market | 19,513 | 16,497 | 26 | 3 |
| uni lines | 11,618 | 11,602 | 22 | 6 |
| flood | 26,142 | 22,413 | 24 | 11 |
| Line 1 (full year) | 55,673 | 55,665 | 28 | 2 |

**Checks applied:** no trip spans more than one `line` / `direction` /
origin / destination; productive trips have a sensible stop count; every
remaining one-stop trip is **non-productive** (deadhead / depot positioning),
i.e. ≤0.05 % of productive trips are artifacts.

---

## Known limitations

- **~0.4 % same-route recurrences stay merged.** If a block runs the exact same
  `(line, direction, origin, destination)` twice in a row with no intervening
  trip, the two runs share a `trip_id`. Rare in real schedules; not corrected.
- **`vehicle_block` is a duty, not a physical bus.** It is the finest vehicle
  grouping available — there is still no true vehicle/VIN id.
- **Non-productive rows get trip_ids too.** Deadhead/depot moves form their own
  (mostly one-stop) trips. Filter on `productive_dep` for passenger analysis.
- **Line-1 export gaps cascade.** Months missing `stop_code`/`stop_point`
  (see `DATA_DEFECTS.md` §4) still get correct `trip_id`s — the key uses
  `trip_start_code`/`trip_end_code`, which are always present.
