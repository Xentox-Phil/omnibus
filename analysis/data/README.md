# `analysis/data/` — data layout

**Nothing in here is committed to git** except this README and the folder skeleton
(`.gitkeep` files). Raw RVV data is not redistributable; parquet is regenerable.
Get the raw files from a teammate (shared drive / USB), drop them into the exact
paths below, then run the pipeline to rebuild `parquet/`.

```
analysis/data/
├── raw/                      # source inputs — you provide these
│   ├── rvv/                  # RVV ITCS exports (UTF-16 CSV, German columns)
│   │   ├── 06.10.2024_19.10.2024_ITCS.csv
│   │   ├── 08.10.2023_21.10.2023_ITCS.csv
│   │   ├── 15.12.2024_25.12.2024_ITCS_Christkindlmarkt2024.csv
│   │   ├── 23.04.2025_09.05.2025_ITCS_nur_UniLinien.csv
│   │   ├── 26.05.2024_07.06.2024_ITCS_Hochwasser.csv
│   │   └── Daten Linie 1/     # UNZIP "Daten Linie 1_….zip" into this folder (12 monthly CSVs)
│   │       └── SQ-S02 Linie 1 2024-09-01 bis 2024-09-30.csv  (… through 2025-08)
│   ├── oth_ics/              # OTH semester calendars (.ics) — COMMITTED (fragile upstream)
│   └── events_regensburg_2024_2025.csv
└── parquet/                  # BUILT — do not hand-edit, regenerate from pipeline
```

## Dropping in RVV data (must match exactly)

The ingest script keys off **filenames**, so keep them byte-for-byte:

| File / folder | What it is |
| ------------- | ---------- |
| `06.10.2024_19.10.2024_ITCS.csv` | 2-week baseline (07.–14.10. OTH only, 15.–18.10. OTH+Uni) |
| `08.10.2023_21.10.2023_ITCS.csv` | same window, 2023 (year-over-year baseline) |
| `15.12.2024_25.12.2024_ITCS_Christkindlmarkt2024.csv` | Christmas market event (OTH+Uni) |
| `23.04.2025_09.05.2025_ITCS_nur_UniLinien.csv` | Uni lines only (2, 4, 6, 11, C1/C2/C4/C6, X4) |
| `26.05.2024_07.06.2024_ITCS_Hochwasser.csv` | June 2024 flood (peak 02.06., Meldestufe 4, 5.5 m) |
| `Daten Linie 1/` | **Unzip** `Daten Linie 1_….zip` into this folder → 12 monthly CSVs, full-year 2025 Line 1 |

Notes:
- `ingest.py` reads the **unzipped** `Daten Linie 1/` folder (it does not open zips).
  Extract the RVV zip into `raw/rvv/Daten Linie 1/` before running it.
- CSVs are **UTF-16**, comma-delimited, German column headers. See the root
  [`CLAUDE.md`](../../CLAUDE.md) for the German→English column map and dataset quirks.

## Rebuilding parquet

`uv run python pipeline/ingest.py` (from inside `analysis/`) rebuilds the RVV
parquet; external fetchers fill the rest. Full script list + commands:
[`analysis/README.md`](../README.md#scripts-pipeline).
