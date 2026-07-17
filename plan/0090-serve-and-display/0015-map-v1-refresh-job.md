# 0090.pending - map-v1 refresh job

Type: chore
Branch: chore/0015-map-v1-refresh-job

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Wrap the `map-v1` SF persist + geo persist + stability backfill into one scheduled job that re-runs the full history at a later `--end`.
* Run weekly (matching the 7-day refit cadence) so the served map advances as new DAM days land.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* The map is a batch artifact: the API serves `max(window_start)` for `map-v1`, resolved per request. New rows in `ercot_dam_shadow_prices`/`ercot_dam_spp`/`dam_system_lambda` do **nothing** until a re-persist — the served window stays frozen at the last run's `--end`.
* Re-persist is picked up with no redeploy (per-request run/window resolution, 0004). Weekly is enough — SF structure is fixed per refit and the explorer is not time-indexed, so intra-week staleness is structurally harmless.
* **Footgun:** the runner calls `delete_sf_run(run_id)` first (deletes *all* windows for the run_id), then writes only windows in `[--start, --end)`. A narrow `--start` wipes history. Always pass the full `--start 2025-01-01`. True incremental append (fit only new windows) is unsupported today — a full re-run is ~30 min / ~67M rows.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `ops/deploy/jobs/` (mirror `backfill_ingest_job.yml` / `backfill_outages_job.yml`).
* Chain three steps in one job, in order, full history, later `--end`:
  1. `python -m compute.sf.runner --run-id map-v1 --start 2025-01-01 --end <latest+1> --window-days 240 --refit-days 7 --ridge-lambda 1.0 --min-binding-hours 25 --persist-sf`
  2. `python -m compute.sf.geo_persist --run-id map-v1` — reads each window's SF back from `implied_shift_factors`, upserts `constraint_geo` (idempotent delete-then-copy). No date args: it locates whatever windows step 1 persisted.
  3. `python -m compute.sf.eval --run-id map-v1 --start 2025-01-01 --end <latest+1> --window-days 240 --ridge-lambda 1.0 --min-binding-hours 25 --persist-eval` (+ the `sf_stability` backfill from 0003 Commit D)
* `--ridge-lambda 1.0` explicit: module default is `1e-1`; adopted operating point is λ=1.0.
* Cadence: weekly. `--end` = latest legal DAM day + 1 (exclusive).
* Do NOT touch: `--persist`/`--promote`/`implied_binding_proximity` (legacy bp path); the fitting code.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] A weekly job re-runs all three steps over full history under `map-v1`.
* [ ] After a run, `max(window_start)` in `sf_window_meta` for `map-v1` advances to cover the new `--end`; the API serves it without redeploy.
* [ ] `constraint_geo` + `sf_window_meta.sf_stability` are populated for the new latest window.
* [ ] No legacy binding-proximity rows written under `map-v1`.
