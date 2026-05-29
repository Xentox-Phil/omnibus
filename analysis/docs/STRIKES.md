# Labor Strikes Affecting RVV / Regensburg Bus Operations, 2024–2025

## TL;DR — the boring truth

**No ver.di bus driver strikes hit das.Stadtwerk Mobilität / RVV city buses in 2024 or 2025.**

The reason is structural: Regensburg city bus drivers are paid under **TV-N Bayern** (the Bavarian Nahverkehr collective agreement). That contract was extended in 2023 and was **not** terminated again until late 2025, so the **Friedenspflicht** (peace obligation under §74 BetrVG/TVG) was in effect throughout 2024 and 2025. Ver.di explicitly stated "Kein Streik in Bayern" for the nationwide ÖPNV Warnstreik wave of Feb/Mar 2024.

The first wave of Regensburg city bus strikes in this dispute cycle began on **2 February 2026** — outside this analysis window.

The strikes that *did* hit Regensburg in 2025 were under **TVöD (Bund + Kommunen)** and **TV-V (Versorgung)** — they affected city admin, Kitas, REWAG, Regensburg Netz, Müllabfuhr, MedBO, etc. Bus drivers were **not** on the strike call lists. These are included in the CSV with `affected_service=unknown` and `medium`/`low` confidence — they might cause minor downstream effects (e.g. a striking dispatcher, an unstaffed depot office) but are unlikely to produce headline cancellations in the ITCS telemetry.

---

## Search methodology

### Queries run (all via WebSearch)

- `ver.di Warnstreik RVV Regensburg 2024 Busverkehr Stadtwerke`
- `TV-N Bayern Warnstreik 2024 Regensburg ÖPNV Busse`
- `ver.di Warnstreik ÖPNV Bayern März 2024 Regensburg Stadtbus`
- `ver.di Warnstreik Februar 2024 ÖPNV nationwide Regensburg`
- `Stadtwerk Regensburg Warnstreik 2025 Bus Streik`
- `"Bayern" "ÖPNV" Warnstreik 2024 ausgenommen TV-N nicht gekündigt`
- `verdi Streiks 2024 Übersicht Bayern ÖPNV nicht gestreikt Friedenspflicht TV-N`
- `"Regensburg" TVöD Warnstreik 2025 Stadtwerke öffentlicher Dienst`
- `"Regensburg" "13. Februar 2025" verdi Warnstreik Stadtverwaltung Bus`
- `"Regensburg" verdi "20. Februar 2025" Warnstreik TV-V Stadtwerke Energie Müll Bus`
- `verdi Tarifrunde 2025 öffentlicher Dienst Bayern ÖPNV nicht betroffen Stadtbus`
- `"Regensburg" Bus Streik "11. März 2025" OR "12. März 2025" verdi Stadtwerke`
- `"Regensburg" Stadtbus verdi Streik "März 2025" OR "April 2025" OR "Mai 2025"`
- `"Regensburg" Streik "Dezember 2024" OR "November 2024" verdi Stadtbus`
- `RBO Regensburg Streik Regionalbus 2024 2025 verdi Privatunternehmen`
- `privater Omnibus Bayern Streik 2024 2025 verdi NWO Regensburg`
- `"Regensburg" "27. März 2023" Warnstreik Bus Stadtwerke verdi ÖPNV` (cross-ref 2023)
- `"Regensburg" Bus Streik Oktober 2023 verdi ÖPNV ausfall` (cross-ref 2023)

### Pages fetched directly (WebFetch)

- https://www.das-stadtwerk-regensburg.de/presse/detail/warnstreik-weitgehender-entfall-des-stadtbusverkehrs-am-montag
- https://www.das-stadtwerk-regensburg.de/presse/detail/warnstreik-massive-einschraenkungen-des-stadtbusverkehr
- https://www.das-stadtwerk-regensburg.de/presse/news (index)
- https://oberpfalz.verdi.de/themen/nachrichten/++co++65a8ade6-ef9f-11ef-a498-90b11c4f1b2d (20.02.2025)
- https://oberpfalz.verdi.de/themen/nachrichten/++co++d29dbb3c-e877-11ef-9f9a-90b11c4f1b2d (13.02.2025)
- https://oberpfalz.verdi.de/themen/nachrichten/++co++a5b88b76-fe64-11ef-bdbf-5fc2ffc6be62 (13.03.2025)
- https://oberpfalz.verdi.de/themen/tarifrunde-oed-2023/++co++00cc66e2-b90a-11ed-86e5-001a4a160111 (3.+8.3.2023 — cross-ref)
- https://oberpfalz.verdi.de/ (index)
- https://www.charivari.com/streiks-im-oeffentlichen-dienst-treffen-heute-regensburg-846054/
- https://www.regensburg.de/aktuelles/pressemitteilungen/.../warnstreik-13-februar-... (404/index only)
- https://www.regensburg.de/aktuelles/pressemitteilungen/.../warnstreik-13-maerz-... (index only)
- https://www.onetz.de/deutschland-welt/regensburg/fortsetzung-warnstreiks-regensburg-auswirkungen-nahverkehr-id3985629.html
- https://www.tvaktuell.com/regensburg-warnstreik-im-oeffentlichen-dienst-am-13-februar-2025-648057/ (headline only, no body extractable)
- https://www.verdi.de/presse/pressemitteilungen/++co++4d58a31e-eea4-11ef-9d12-854c17a86c53 (21.02.2025 ÖPNV — Bayern explicitly excluded)
- https://www.verdi.de/bayern/presse/pressemitteilungen/verdi-ruft-zum-streik-am-20-februar-2025-versorgungs-und-entsorgungsbetrieben-bayernweit
- https://www.oeffentlichen-dienst.de/266-tarifrunde/4066-tarifrunde-tv-n-2024.html (confirms Bayern excluded from TV-N 2024)

### Key reference sources

Primary:
- **ver.di Bezirk Oberpfalz** — `oberpfalz.verdi.de` — local strike call announcements
- **ver.di Landesbezirk Bayern** — `bayern.verdi.de` and `verdi.de/bayern/...`
- **ver.di Bundesebene** — `verdi.de/presse/pressemitteilungen`
- **das Stadtwerk Regensburg** — `das-stadtwerk-regensburg.de/presse/news`
- **Stadt Regensburg Pressemitteilungen** — `regensburg.de/aktuelles/pressemitteilungen` (mostly only index titles indexable; bodies behind JS)
- **RVV** — `rvv.de/neuigkeiten`

Secondary / cross-reference:
- TVA aktuell (`tvaktuell.com`)
- Charivari Regensburg (`charivari.com`)
- Bayerische Staatszeitung (`bayerische-staatszeitung.de`)
- Onetz Oberpfalz (`onetz.de`)
- Mittelbayerische Zeitung (`mittelbayerische.de`) — paywalled, low yield
- Bayerischer Rundfunk (`br.de`) — checked, no specific 2024/2025 RVV bus strike found

---

## Strike-by-strike findings

### 2024 — Friedenspflicht in Bayern ÖPNV

| Period | Finding |
|---|---|
| Feb 2024 nationwide ÖPNV Warnstreik | **Bayern explicitly excluded.** Ver.di press release: "Aufgrund abweichender Tarifvertragslaufzeiten gilt dies jedoch nicht für Bayern... daher herrscht im bayerischen ÖPNV die Friedenspflicht." |
| 1 March 2024 "Klimastreik" | National TV-N action — Bayern out. |
| Throughout 2024 | TVöD round 2023 already concluded (April 2023). No public-service strike wave in 2024 calendar year affecting Regensburg. |
| Christmas market period (Dec 2024) | No strikes found. |

**Conclusion: No CSV rows for 2024.**

### 2025 — TVöD + TV-V waves; ÖPNV still in Friedenspflicht

| Date | Wave | RVV bus impact |
|---|---|---|
| 13 Feb 2025 | TVöD (Bund + Kommunen) round 1 follow-up | Kitas, MedBO, Müll, Westbad. Buses NOT on call list (TV-N). Included as CSV row with caveat. |
| 20 Feb 2025 | TV-V (Versorgung + Entsorgung) bayernweit | REWAG, Regensburg Netz, "das.Stadtwerk Regensburg Fahrzeuge und Technik" (Werkstatt), ZMS Schwandorf. NOT das.Stadtwerk Mobilität / Fahrdienst. Included with caveat. |
| 21 Feb 2025 | TVöD ÖPNV-Warnstreik in 6 Bundesländern (BW, HB, HE, NI, NRW, RP) — **Bayern not in list** | No RVV impact. |
| 13 Mar 2025 | TVöD round 3 follow-up | Stadtverwaltung, Stadtwerke (general), Kitas, Kliniken, Pflege, US-Garnisonen. Buses not explicitly named. Included with caveat. |
| Spring/Summer 2025 | None found targeting RVV / das.Stadtwerk Mobilität |

**Conclusion: 3 CSV rows for 2025, all `medium`/`unknown` regarding actual bus service impact.**

---

## Cross-reference (out of scope but useful)

These dates are NOT in the CSV (outside 2024–2025 window) but should be flagged when joining onto datasets:

- **27 March 2023** — verdi + EVG nationwide Großstreiktag. RVV explicit: "massive Auswirkungen auf Zug- und Busverkehr im RVV-Gebiet" — all das.Stadtwerk.Mobilität trips cancelled. Source: `landkreis-regensburg.de/...warnstreik-am-montag-den-27-maerz-2023-...`
- **3 March 2023** — verdi TVöD strike — Stadtwerke + das.Stadtwerk Mobilität jointly. Source: `oberpfalz.verdi.de/themen/tarifrunde-oed-2023/...`
- **8 March 2023** — verdi strike continuation, Regensburg (Müllabfuhr, Verwaltung). Source: same.
- **19 May 2023** — TV-N Bayern Warnstreik in Bayern — Regensburg city buses fully cancelled. (Last TV-N strike before 2026 round.)
- **21 March 2023** — Stadtbus Warnstreik. Source: `tvaktuell.com/regensburg-warnstreik-keine-stadtbusse-am-21-03-535291/`
- **2 February 2026** — TV-N Bayern Warnstreik. Full Stadtbus shutdown 03:00–03:00. (First strike of the 2026 round.)
- **19–20 February 2026** — TV-N Bayern Warnstreik, 2-day. Stadtbus near-full shutdown.
- **14 April 2026** — TV-N Bayern Warnstreik, full day. Notkonzept in place.

The Oct 2023 ITCS sample (`08.10.2023_21.10.2023_ITCS.csv`) — no strikes found in that fortnight.

---

## Known gaps / what we couldn't confirm

1. **Regensburg.de press releases** — the city's CMS renders bodies via JS, so WebFetch only got index pages. Two press releases (titled `dienstleistungsgewerkschaft-ver-di-ruft-fuer-den-13-februar-...zu-warnstreik-auf` and `...13-maerz-...`) confirmed by URL slug but body content not extractable. Title alone confirms 13 Feb 2025 + 13 Mar 2025 calls existed and targeted "Beschäftigte aus allen Bereichen der Stadtverwaltung" — but "Stadtverwaltung" does not include das.Stadtwerk Mobilität GmbH as a subsidiary.
2. **Did Mobilität admin/dispatcher staff actually strike on 13.02 / 20.02 / 13.03 2025?** Unconfirmed. The strike call lists do not name Mobilität-Fahrdienst, but "Stadtwerke" generically appears on 13.03.2025. Search did not surface a "Stadtbusse fahren trotz Streik normal" disclaimer either.
3. **Private regional bus operators** (RBO Regensburger Omnibus GmbH, Pacher, Watzinger, Pilgermayer, Bachl) — the BBOG/NWO private omnibus tariff round in 2024 affected Baden-Württemberg, Sachsen, RLP. No Bavarian private omnibus strike confirmed for 2024/2025 affecting RVV regional lines.
4. **Mittelbayerische Zeitung** — primary local newspaper; mostly paywalled. Some Wikipedia/Google snippet hints but nothing extractable that contradicted the verdi/Stadtwerke primary sources.
5. **MZ / BR.de archive for 2024 Regensburg-only bus events** — no positive find, but search engines have known recency bias.

---

## How to extend

When a future strike happens:

1. Check `https://www.das-stadtwerk-regensburg.de/presse/news` for an official Mobilität press release — the headline pattern is `Warnstreik: ...Stadtbusverkehr...`. The press release date and the strike day are usually 1–3 days apart.
2. Cross-check `https://oberpfalz.verdi.de/themen/nachrichten/` for the ver.di call.
3. For nationwide context, `https://www.verdi.de/bayern/presse/pressemitteilungen` lists Bayern-wide calls.
4. RVV often publishes a parallel notice: `https://www.rvv.de/neuigkeiten` (and per-strike URLs like `/warnstreik-14-04-2026`).
5. Add a row per strike day. If a strike spans multiple consecutive days, write **one row per ISO date** (CSV convention here).
6. Confidence rule: `high` only if a Stadtwerke or ver.di press release names the date AND names das.Stadtwerk Mobilität / Stadtbus explicitly. Otherwise `medium` with a note explaining why bus service may or may not have been affected.
7. Update this doc's "Cross-reference" section if the new strike falls outside the 2024–2025 window but is useful context.

## Schema reminder

```
date           ISO YYYY-MM-DD, one row per day
duration       full_day | partial | warning_strike | unknown
scope          national | bayern | regensburg_local | rvv_specific
affected_service  buses_all | buses_partial | trams_buses | unknown
description    1-line DE/EN
source_url
source_title
confidence     high | medium | low
notes          optional caveats
```
