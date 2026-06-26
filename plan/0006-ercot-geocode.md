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
* Step 5 — Match each SP through six passes (first hit wins):
  1. exact lookup vs LMP designation (with `BAC_BAC_*` prefix-dedup retry)
  2. fuzzy ≥85 vs EIA Plant Name OR unique Utility Name using ERCOT's
     `Generator Station Description` (Stand-Alone Generation Resources
     report). Bridge: `{UNIT_SUBSTATION}_{UNIT_NAME}` → unit code →
     station description (a real plant name) → match against EIA. The
     utility-name pool is restricted to utilities owning exactly one
     plant (≈84% of utilities) so multi-plant aggregators like NRG /
     Calpine / Engie can't collapse unrelated SPs onto one arbitrary
     plant. This is essential because the description often matches
     `Utility Name` rather than `Plant Name` (e.g. `BVE_UNIT1` →
     "Brazos Valley Energy" → Jack Fusco Energy Center).
  * Ambiguity guard on every fuzzy pass: `token_set_ratio` rewards
     subset matches, so a generic single-token query like `"CALPINE"`
     scores 100 against every unique utility containing it
     (Calpine-Hidalgo, Calpine-Magic Valley, …). When multiple distinct
     compatible plants tie at the top score (±1), the query is skipped
     rather than picking one arbitrarily — wrong coordinates 200+ miles
     away are worse than no coordinates for downstream analysis.
  * Capacity tiebreaker on the ambiguity guard: if the tied plants share
     at least one `plant_name_norm` token (i.e. they're variants of the
     same site like Buffalo Gap I/II/III), and the SP has an expected
     Nameplate (summed from stand-alone Unit Codes), pick the plant
     whose summed nameplate is closest. The token-overlap check is what
     keeps Calpine-style cross-site ties from being silently picked.
  3. fuzzy ≥92 (tight) vs EIA Plant Name OR unique Utility Name using
     owner/DME corporate entities from the ResDMEList report. Same
     `{substation}_{unit_name}` bridge → `OWNER RE` / `DME` strings
     (stripped of `(RE)`/`(DME)` and normalized through stop-tokens like
     `LLC`/`LP`/`INC`/`STORAGE`). Tight threshold because owner ≠
     operator can easily conflate; the source filter further guards
     against e.g. a battery-storage owner resolving to a co-located
     wind farm.
  * Substation-prefix fallback on passes 2–3: when an SP has no entries
     in `Resource_Node_to_Unit` (common for PCCRN-style SPs like
     `QALSW_CC1`), fall back to its first-underscore prefix and look it
     up directly against the stand-alone report's `Generator Station
     Code` and the DME report's `RESOURCE NAME` prefix. Safe because
     both fields are 1:1 with a single station description / owner
     within the data.
  4. fuzzy `token_set_ratio` ≥85 vs LMP designation tokens (queries: SP
     name + linked substation names + unit names)
  5. fuzzy ≥85 vs EIA Plant Name
  6. plant-name substring fallback
  * 70–84 → review queue (no coords emitted; bad matches with high partial
    overlap would otherwise pollute downstream joins).
  * Energy-source compatibility filter on all fuzzy/substring passes:
    infer a source (solar/wind/battery/gas/coal/...) from the stand-alone
    report's `Generator Type` when available, else the DME report's
    `TYPE=Storage` (battery), else from SP + unit-name tokens (`SLR`,
    `WND`, `BESS`/`ESR`, `CC`/`CT`/`GT`/`NG`, …); compare against EIA
    `Technology` + `Energy Source 1`. Hits whose plant source disagrees
    are rejected, falling through to the next-best candidate. Either
    side `None` is treated as compatible so unknown-source SPs still
    match.
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
      `[settlement_point, sp_type, lat, lon, match_method, match_confidence,
      matched_plant, matched_capacity_mw, station_description, owner_re,
      expected_mw, capacity_ratio]`. (804 rows; only LMP/station-
      description/owner-name/fuzzy/substring/manual matches emit coords.
      Trailing context columns let a reviewer eyeball matches at a
      glance: `capacity_ratio = expected_mw / matched_capacity_mw`
      flags unit-of-plant (≪1, normal), whole-plant (~1), and
      cross-plant or multi-phase aggregation (≫2 — worth review).)
* [x] `data/processed/hubs_lz_centroids.csv` exists covering all 8 ERCOT
      Load Zones (incl. NOIE) and 7 Hubs.
* [x] ≥ 80% auto-match rate on top-200-by-capacity RNs; remainder
      substring-matched or in `data/raw/ercot_geocode/review_queue.csv`.
      (Achieved 98.0%: 196 auto + 4 substring of 200 head rows; 223 RNs
      with mapped capacity, 0 unmatched in head. Earlier iterations:
      removed ~110 false positives from orphan-token over-matching,
      narrowed by energy-source compatibility filter, lifted by the
      station-description bridge, strengthened by EIA-860 2025 early
      release data, lifted further by the owner/DME tight-match pass,
      then by the substation-prefix fallback for PCCRN-style SPs, then
      by adding Utility Name (unique-only) to the search pool, then
      tightened by an ambiguity guard that rejects unrelated ties at
      top score, and finally by a capacity-based tiebreaker that
      resolves same-site variants like Buffalo Gap I/II/III.)
* [x] Run log records counts per match method and unmatched count.
