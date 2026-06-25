# ERCOT geocoded layer

Type: feat
Branch: feat/0006-ERCOT-geocode

## Goal

* Build `settlement_points_geocoded.csv` mapping priced ERCOT settlement points to lat/lon.
* Hand-geocode the Hub and Load Zone centroids into a separate companion file.
* Emit match-rate stats and a low-confidence review queue for manual QA.

## Context

* Phase 0 established the project scaffold; no spatial layer exists yet.
* All downstream phases (constraint mapping, congestion attribution, forecasting) require settlement points joined to coordinates.
* ERCOT publishes no lat/lon for settlement points — geocoding must come from EIA-860 via fuzzy name matching, with known noise in unit naming conventions.

## Approach

* Code in `preprocess/`, raw inputs in `data/raw/ercot_geocode/`, outputs in
  `data/processed/`.
* Entry point: `preprocess/geocode_ercot_layer.py` (orchestrator, idempotent).
  * Prereq: `master_eia860.csv` produced by `preprocess/extract_eia860.py`
    (one row per TX-operating generator with Plant Name, lat/lon, capacity,
    and `RTO/ISO LMP Node Designation`). Consumed directly — no re-extraction.
* Step 1 — Read priced SPs from CDR LMP snapshot
  (`cdr.*LMPSROSNODENP6788*.csv`); the `SettlementPoint` column is the
  resource universe. Other files in the directory (`Settlement_Points`,
  `NOIE_Mapping`) carry topology metadata that isn't needed for the geocoded
  layer itself.
* Step 2 — Drop `HB_/DC_/LZ_` (hubs, DC ties, load zones go to centroids
  file). Classify the rest:
  * `PCCRN` if name appears in `CCP_Resource_Names`
  * `PUN` if suffix `_PUN\d*`
  * `RN`  if suffix `_RN\d*`
  * `OTHER` otherwise (catches LCCRN-style and unsuffixed CC names)
* Step 3 — Aggregate `master_eia860.csv` to plant level (sum nameplate
  capacity; concat LMP designations).
* Step 4 — Normalize names on both sides (uppercase; strip unit suffixes
  `_RN`, `_PUN\d*`, `_UNIT_?\d+`, `_G\d+`, `_CC\d+`, `_BESS\d*`, `_ESR\d*`,
  `_ALL`, …; drop generic tokens like `WIND`/`SOLAR`/`STATION`/`UNIT`/`GEN`).
  Queries shorter than 4 chars or with no alpha token of length ≥3 are
  rejected — without this guard, orphan tokens like `"1"` (from `SOLAR1`)
  or `"UNIT"` (from `UNIT_1`) score 100% via `token_set_ratio` against any
  LMP designation containing those tokens and collapse dozens of unrelated
  SPs onto one plant.
* Step 5 — Match each SP through five passes (first hit wins):
  1. exact lookup vs LMP designation (with `BAC_BAC_*` prefix-dedup retry)
  2. fuzzy ≥85 vs EIA Plant Name using ERCOT's `Generator Station
     Description` (Stand-Alone Generation Resources report). Bridge:
     `{UNIT_SUBSTATION}_{UNIT_NAME}` → unit code → station description (a
     real plant name) → match against EIA Plant Name. Highest-quality
     pass since both sides are full names rather than cryptic codes.
  3. fuzzy `token_set_ratio` ≥85 vs LMP designation tokens (queries: SP
     name + linked substation names + unit names)
  4. fuzzy ≥85 vs EIA Plant Name
  5. plant-name substring fallback
  * 70–84 → review queue (no coords emitted; bad matches with high partial
    overlap would otherwise pollute downstream joins).
  * Energy-source compatibility filter on all fuzzy/substring passes:
    infer a source (solar/wind/battery/gas/coal/...) from the stand-alone
    report's `Generator Type` when available, else from SP + unit-name
    tokens (`SLR`, `WND`, `BESS`/`ESR`, `CC`/`CT`/`GT`/`NG`, …); compare
    against EIA `Technology` + `Energy Source 1`. Hits whose plant source
    disagrees are rejected, falling through to the next-best candidate.
    Either side `None` is treated as compatible so unknown-source SPs
    still match.
* Step 6 — Apply manual overrides from
  `data/raw/ercot_geocode/manual_overrides.csv` (git-tracked, same schema
  as the geocoded output). Reviewed entries land here; reruns refresh the
  auto layer without clobbering them. Overridden SPs drop out of the
  review queue; stale entries are warned.
* Step 7 — Top-N metric: rank RNs with mapped EIA capacity > 0 by
  capacity, take head ~200. (Zero-capacity unmatched RNs are not padded
  into the rank.)
* Step 8 — Hand-geocode Hubs and Load Zones into
  `data/processed/hubs_lz_centroids.csv`.
* Do NOT touch: SPP price ingestion, constraint parsing, or any modeling
  code — deferred to later phases.

## Acceptance

* [x] `data/processed/settlement_points_geocoded.csv` exists with columns
      `[settlement_point, sp_type, lat, lon, match_method, match_confidence]`.
      (604 rows; only LMP/station-description/fuzzy/substring/manual
      matches emit coords.)
* [x] `data/processed/hubs_lz_centroids.csv` exists covering all 8 ERCOT
      Load Zones (incl. NOIE) and 7 Hubs.
* [x] ≥ 80% auto-match rate on top-200-by-capacity RNs; remainder
      substring-matched or in `data/raw/ercot_geocode/review_queue.csv`.
      (Achieved 93.3%: 126 auto + 9 substring of 135 head rows; 0
      unmatched in head. Earlier iterations: removed ~110 false positives
      from orphan-token over-matching, narrowed by energy-source
      compatibility filter, lifted by the station-description bridge,
      then strengthened by adding EIA-860 2025 early release data.)
* [x] Run log records counts per match method and unmatched count.
