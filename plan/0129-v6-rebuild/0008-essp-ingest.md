# 0129-0008 - essp-ingest

Type: feat
Branch: feat/0129-0008-essp-ingest
Depends on: none

## Goal

* Add NP4-158-SG (DAM Electrically Similar Settlement Points) as an archive
  ingest feed, retaining its pre-DAM study and post-DAM final vintages.
* Land hourly settlement-point → group rows into a new `ercot_essp`
  hypertable, keyed `(interval_ts, settlement_point, is_study, dst_flag)`.
* Make the selected hourly ESSP vintage available to the v6 node panel and
  constraint footprint map, so they can collapse electrically identical points
  **before the DAM clears**.
* Emit a daily implied-SF agreement score against the ESSP grouping, and log it
  per delivery day so it can be charted.

## Context

* ESSPs are settlement points ERCOT's network model treats as one electrical
  location. They price identically: verified 2026-08-11 against the JUL2026 CRR
  auction (identical `ShadowPricePerMWH` to 6 dp) and against DAM SPP for
  2026-07-28 (max hourly |Δ| = 0.000000).
* **Why not just derive it from prices.** Exact 24-hour SPP identity is a
  strictly *wider* relation than ESSP — 35 groups / 86 nodes vs 27 / 60 on the
  cast's 177 points — and it is exact. But it is only knowable **after the DAM
  clears**. The brief's forecast-only view has no grouping at all today, and
  that is the view a reader sees every morning before 13:30. ESSP is published
  **prior to 0600 as a DAM study**, which is the only pre-clearing source of
  this relation that exists.
* The two sources are therefore complementary, not redundant, and the panel
  should use ESSP pre-clearing and price identity post-clearing.
* Without this, the node panel spends multiple top-15 slots on one location: on
  2026-07-28, `BAFFIN_ALL`/`PENA_ALL`/`STELLA_RN`/`TGW_T1_T2` occupied four of
  the top eleven rows at an identical −$24.80, and the existing lat/lon dedupe
  cannot see it — those four sit at four distinct coordinates.
* **Membership is per-hour and moves with topology and outages.** It is a
  property of a delivery hour, not of a node, and must not be cached across
  days. The original 2026-07-28 145→146 observation could not be reproduced
  from ERCOT's currently archived study or final files: both report
  `BAFFIN_ALL` in group 146 at HE18 and HE19. A rotating weekly sample over
  roughly two months found membership stable for about 99.2% of comparable
  point-hours, but not perfectly stable; that is evidence for hourly storage,
  not a static cache.
* Report is public, no certification. Report type ID `13058`, EMIL `np4-158-sg`,
  generation frequency "Event - Per DAM Run", first run 2011-12-09.
* CSV columns confirmed from a downloaded file:
  `DeliveryDate, HourEnding, SettlementPoint, GroupIndex, UpdateTime, DSTFlag`.
  `GroupIndex` is an integer group label, reused across days — it is **not** a
  stable identifier for a group's membership over time.

## Approach

* Work in: `ercot_ingest/`, `db/migrations/`, `ops/deploy/jobs/`,
  `ops/deploy/backfills.sh`.
* Entry point / primary change: `load_essp` in `loaders.py` and the dedicated
  `backfill_essp.py` archive driver. This is intentionally **not** an
  `ENDPOINTS` entry in `backfill.py`: NP4-158-SG is a ZIP/CSV archive product
  with two posting-time-selected documents for a delivery date, like the
  outages driver, rather than a paged JSON feed with a reusable request body.

* **Transport — resolved.** The public JSON route did not provide this report;
  use the authenticated ERCOT archive index and archive download transport.
  The MIS report listing remains useful for product inspection:
  * list: `https://www.ercot.com/misapp/GetReports.do?reportTypeId=13058`
  * file: `https://www.ercot.com/misdownload/servlets/mirDownload?mimic_duns=000000000&doclookupId=<id>`
  * CSV arrives zipped; two files land for a delivery day (the pre-0600 study
    and the post-DAM enforced/final list), posted on D-1. The driver asks the
    archive index for that posting day, selects the latest document before
    10:00 CT as `essp_study` and the latest after it as `essp_final`, and reads
    its one CSV member with `pd.read_csv`.
  * Retain both vintages. The study is the causal forecast-only source; the
    final is the settled validation source. Do not overwrite study with final:
    ERCOT can add/remove points as DAM topology and outages are resolved.
  * `ingest_log` tracks `essp_study` and `essp_final` separately. The recurring
    15-minute `live_updater` calls the driver's self-throttling `update_recent`;
    it does no archive request once both vintages for a day are logged. ESSP is
    therefore not put in `LAGGED`, whose multi-day JSON-report semantics do not
    apply.

* **Migration** — `db/migrations/40_essp.sql`:
  * Model after `db/migrations/12_dam_spp.sql` (hypertable).
  * Columns: `interval_ts TIMESTAMPTZ NOT NULL`, `dst_flag BOOLEAN NOT NULL
    DEFAULT FALSE`, `settlement_point TEXT NOT NULL`, `group_index INT NOT
    NULL`, `is_study BOOLEAN NOT NULL DEFAULT FALSE`, `updated_at TIMESTAMPTZ`.
  * Primary key `(interval_ts, settlement_point, is_study, dst_flag)`.
  * Index on `(interval_ts, group_index)` — group lookups are the read path.
  * Do NOT store a derived "anchor" column. The anchor is a presentation choice
    and belongs in the serving layer, not the store.

* **Serving — query endpoint, not legacy blob.** `GET /analysis/essp` accepts
  an offset-bearing `interval_ts` and explicit `source=study|final`, returning
  all members by `group_index` for precisely that vintage/hour. It soft-fails
  with `essp_missing`; it deliberately has no cross-day or cross-vintage
  fallback. This follows the v6 query-endpoint architecture in the index and
  keeps `analysis_brief` untouched.
  * The v6 page selects its own peak hour, requests `study` in forecast mode
    and `final` in settled mode, then picks the alphabetically first member
    *present in the panel's data* as anchor. It draws one footprint marker and
    one node row per returned group. This UI wiring belongs to `0009`; no
    static `GroupIndex` identity may cross an hour or delivery day.

* **Scoring the implied-SF model.** ESSP is a free labelled test set for
  `implied_shift_factors`: any two settlement points in the same ESSP group must
  have the same SF row. Compute per delivery day:
  * `essp_precision` — of the groups the SF signature declares identical, the
    share that fall inside one ESSP group. Measured 2026-08-11 on one day:
    **20 of 20, zero splits**, 10 of the 20 sharing no name prefix.
  * `essp_recall` — of ESSP groups whose members all appear in the SF matrix,
    the share the SF signature also declares identical. This is the harder and
    more informative number; precision alone can be gamed by declaring almost
    nothing identical. The served 2026-07-28 artifact produced `1.0` precision
    and `0.605555...` recall against final ESSP labels.
  * Land both in `scoreboard_daily` (migration `41_scoreboard_daily_essp.sql`)
    so they accumulate without a new table.
  * **Open question for the user — do not decide this in implementation.** Where
    does this score belong? It is a model-accuracy metric against external
    ground truth, which is a different claim from the existing forecast-accuracy
    track record, and the two should probably not share a strip. Candidates: the
    brief's header track strip, a row in the data-status table, or its own
    panel on a methodology/scoreboard page. Bring a proposal before building UI.

* Do NOT touch: `implied_shift_factors` or the SF fitting code. This plan
  ingests a validation set and a display grouping; it does not feed ESSP back
  into the model as a constraint. Doing so would destroy the independence that
  makes the score meaningful.

## Acceptance

* [x] `ercot_essp` hypertable exists with the migration-40 columns and primary
      key `(interval_ts, settlement_point, is_study, dst_flag)`.
* [x] Dedicated `backfill_essp.py --resume` uses the archive ZIP/CSV driver and
      separately records `essp_study` / `essp_final` delivery-date windows in
      `ingest_log`. A full 2025-01-01-onward historical run remains operational
      work, not a prerequisite for serving already ingested days.
* [x] The repeating live updater calls the self-throttling archive driver and
      retains both pre-0600 study and post-DAM final files via `is_study`.
* [x] Spot check 2026-07-28 HE16: 484 settlement points across 181 groups;
      `BYP_RN`, `HEN_RN`, `WAP_WAP_G6`, `WAP_WAP_G7` share one `group_index`.
* [x] Spot check the 2026-07-28 report currently available from ERCOT:
      `BAFFIN_ALL` is group 146 at HE18 and HE19. Retain the hourly key — this
      check supersedes the earlier 145→146 move observation, which is not present
      in the current archived study or post-DAM files.
* [x] `/analysis/essp` serves explicit study/final hourly membership and typed
      web-client contracts, with tests covering both vintages, missing data,
      and offset-required timestamps.
* [x] The v6 node panel collapses the delivery peak-hour ESSP groups to one row
      with a member count, choosing the alphabetical canonical member. It prefers
      post-DAM final membership and falls back to study when final is absent. The
      2026-08-12 local production slice reduces 1,119 raw nodes to 814 groups;
      `OLNEYTN_AGR1 ≈2` and `BAFFIN_ALL ≈2` appear in the top-15 screen.
* [ ] The v6 constraint footprint map draws one marker per selected ESSP group.
      Deferred to `0009-brief-page-v6`.
* [x] `essp_precision` and `essp_recall` are model-only `scoreboard_daily`
      fields, calculated by the normal `daily_forecast` grading tick from the
      persisted served SF artifact and post-DAM final labels. No separate
      recurring score/backfill job was added. A local 2026-07-28 artifact check
      yielded precision `1.0` and recall `0.605555...`.
* [x] `implied_shift_factors` and SF fitting code are unchanged; ESSP is only a
      raw display grouping and an independent validation label.
