# 0129-0008 - essp-ingest

Type: feat
Branch: feat/0129-0008-essp-ingest
Depends on: none

## Goal

* Add NP4-158-SG (DAM Electrically Similar Settlement Points) as a new ingest
  endpoint, following the NP4-191-CD pattern end-to-end.
* Land hourly settlement-point → group rows into a new `ercot_essp`
  hypertable, keyed `(interval_ts, settlement_point)`.
* Collapse electrically identical settlement points to one row in the daily
  brief's node panel and constraint footprint map, **before the DAM clears**.
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
  days. On 2026-07-28 `BAFFIN_ALL` moved from group 145 to 146 at HE19.
* Report is public, no certification. Report type ID `13058`, EMIL `np4-158-sg`,
  generation frequency "Event - Per DAM Run", first run 2011-12-09.
* CSV columns confirmed from a downloaded file:
  `DeliveryDate, HourEnding, SettlementPoint, GroupIndex, UpdateTime, DSTFlag`.
  `GroupIndex` is an integer group label, reused across days — it is **not** a
  stable identifier for a group's membership over time.

## Approach

* Work in: `ercot_ingest/`, `db/migrations/`, `ops/deploy/jobs/`,
  `ops/deploy/backfills.sh`.
* Entry point / primary change: new `load_essp` in `loaders.py`, new `essp`
  entry in `ENDPOINTS` in `backfill.py`, new live-window fetch block in
  `ErcotClient.py`.

* **Endpoint route — resolve this first.** Confirm whether the pubapi exposes
  `/np4-158-sg/...` through `PROXY_BASE`. If it does, use it, identically to
  `/np4-191-cd/dam_shadow_prices`. If it does not, fall back to the MIS report
  listing, which is verified reachable unauthenticated:
  * list: `https://www.ercot.com/misapp/GetReports.do?reportTypeId=13058`
  * file: `https://www.ercot.com/misdownload/servlets/mirDownload?mimic_duns=000000000&doclookupId=<id>`
  * CSV arrives zipped; two files land per day (the pre-0600 study and the
    post-DAM final). **Prefer the post-DAM file for a settled day; the pre-0600
    file is the one the morning brief must use.** Record which one a row came
    from — they can disagree.

* **Migration** — `db/migrations/39_essp.sql`:
  * Model after `db/migrations/12_dam_spp.sql` (hypertable).
  * Columns: `interval_ts TIMESTAMPTZ NOT NULL`, `dst_flag BOOLEAN NOT NULL
    DEFAULT FALSE`, `settlement_point TEXT NOT NULL`, `group_index INT NOT
    NULL`, `is_study BOOLEAN NOT NULL DEFAULT FALSE`, `updated_at TIMESTAMPTZ`.
  * Primary key `(interval_ts, settlement_point, is_study, dst_flag)`.
  * Index on `(interval_ts, group_index)` — group lookups are the read path.
  * Do NOT store a derived "anchor" column. The anchor is a presentation choice
    and belongs in the serving layer, not the store.

* **Serving** — add ESSP groups to the daily-brief payload for the delivery
  day's peak hour, alongside the existing node lists. Group members and a count
  are enough; the anchor is picked at render time as the alphabetically first
  member *present in the panel's data*, so row identity never flips when prices
  move or the forecast/settled toggle flips.

* **Scoring the implied-SF model.** ESSP is a free labelled test set for
  `implied_shift_factors`: any two settlement points in the same ESSP group must
  have the same SF row. Compute per delivery day:
  * `essp_precision` — of the groups the SF signature declares identical, the
    share that fall inside one ESSP group. Measured 2026-08-11 on one day:
    **20 of 20, zero splits**, 10 of the 20 sharing no name prefix.
  * `essp_recall` — of ESSP groups whose members all appear in the SF matrix,
    the share the SF signature also declares identical. **Unmeasured.** This is
    the harder and more informative number; precision alone can be gamed by
    declaring almost nothing identical.
  * Land both in `scoreboard_daily` (see `db/migrations/36_scoreboard_daily.sql`)
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

* [ ] `ercot_essp` hypertable exists; `\d ercot_essp` matches the columns above.
* [ ] `essp` present in `ENDPOINTS`; `--resume` backfill runs clean over
      2025-01-01 onward and `ingest_log` records the windows.
* [ ] Live job lands both the pre-0600 study file and the post-DAM file for a
      delivery day, distinguished by `is_study`.
* [ ] Spot check 2026-07-28 HE16: 483 settlement points across 180 groups;
      `BYP_RN`, `HEN_RN`, `WAP_WAP_G6`, `WAP_WAP_G7` share one `group_index`.
* [ ] Spot check the intraday move: `BAFFIN_ALL` has a different `group_index`
      at HE18 and HE19 on 2026-07-28.
* [ ] Daily brief node panel collapses ESSP groups to one row with a member
      count, in forecast-only mode, sourced from the pre-0600 file.
* [ ] Constraint footprint map draws one marker per ESSP group.
* [ ] `essp_precision` and `essp_recall` written to `scoreboard_daily` for each
      delivery day, and both are non-null for 2026-07-28.
* [ ] No change to `implied_shift_factors` output — diff the SF artifact for a
      known day before and after to confirm.
