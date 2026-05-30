# Contact notes — RVV challenge contact

Domain knowledge from the RVV person running the Hackaburg challenge. This is
**not** in any file in the data bundle — it's what they told us in person, so it
lives here. Append to it as we learn more.

The high-value bit: which `stop_code` values are **not passenger stops**. These
are depot / operational markers the ITCS records like a stop, but no bus picks up
passengers there. They have no `Globale Haltestellen-Kennung` (DHID) in the stop
master, so `fetch_gtfs.py` can't geocode them — by design. `stops_geo.parquet`
tags each with a `kind` so the analysis/frontend layer can exclude them
explicitly instead of treating them as "missing coordinates".

## Depot & operational codes

| `stop_code` | `stop_name` | What it really is | `kind` |
| --- | --- | --- | --- |
| `BTH SMO` | SMO BTH | **RVV's own depot** (Betriebshof). A bus parked here is "ready to be picked up" — start/end of a vehicle block, not a passenger stop. | `depot_rvv` |
| `vor LSt` | vor LSt | **Same place as `BTH SMO`** — "vor Leitstelle" (in front of the control centre). The contact confirmed `SMO BTH == vor LSt`. | `depot_rvv` |
| `RBO` | RBO | **Subcontractor (Subunternehmer) depot** — Regionalbus Ostbayern. RVV runs some lines through subcontractors; their buses start/end at the sub's own yard. | `depot_sub` |
| `SÖLL` | Söllner | Subcontractor depot — Söllner. | `depot_sub` |
| `Wittl` | Wittl | Subcontractor depot — Wittl. | `depot_sub` |
| `EBEN` | Ebenbeck | Subcontractor depot — Ebenbeck. | `depot_sub` |
| `LAS` | Laschinger | Subcontractor depot — Laschinger. | `depot_sub` |
| `WAZ` | Watzinger | Subcontractor depot — Watzinger. | `depot_sub` |
| `HUK` | HUK | Operator / route code, not a passenger stop. | `operational` |
| `LADE` | Kein Zustieg | "Kein Zustieg" = **no boarding**. Has a DHID (`de:09362:192`) but is an operational marker, not a served stop. | `operational` |
| `TEST 1`–`TEST 4` | Testhaltestelle 1–4 | Test stops. | `test` |

> **EMO BTH** — the contact also mentioned `EMO BTH` = "from Regensburg, the
> buses" (i.e. the Regensburg city operator's own depot, sibling of `SMO BTH`).
> It does **not** appear as a `stop_code` in the data we have, so there's no row
> to tag — noted here so we recognise it if it shows up in a future export.

**Why this matters for analysis:** these codes carry ~7,744 stop-events (~0.2%).
A bus block legitimately starts/ends at a depot, so depot rows are real ITCS
records — but they must be excluded from delay/dwell/demand stats (a 6-hour
"dwell" at the depot overnight is not a passenger wait). **`assemble.py` now drops
them automatically** (`stop_kind != 'stop'`), so `features.parquet` contains only
passenger stop-events. The raw window parquets keep them if you ever need the
block boundaries.

## Open items the contact flagged

- **Missing stops in the location matching.** The contact noted some stops
  weren't geocoded. Root cause found: the old gtfs.de name-match missed ~20
  stops. The RVV-native `stop_code → DHID → GTFS` join (see [`GTFS.md`](./GTFS.md))
  now locates **all 310 real passenger stops** (2 via hand-filled OSM coords),
  so this is resolved.
