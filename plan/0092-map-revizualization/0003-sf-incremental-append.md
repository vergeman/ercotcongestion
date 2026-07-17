# 0092 - sf-incremental-append

Type: refactor
Branch: refactor/0092-sf-incremental-append

## Goal

* Replace the map runner's delete-all-then-rewrite with per-window upsert, so a run recomputes only refit boundaries it does not already have.
* Compute the boundary set-difference (grid boundaries minus persisted `sf_window_meta.window_start`) and fit/persist only the new ones.
* Remove the `--start` footgun: a narrow `--start` no longer wipes served history.

## Context

* Today `delete_sf_run(run_id)` deletes ALL `implied_shift_factors` + `sf_window_meta` rows for the run, then rewrites `[--start, --end)` — a full-history re-run every weekly tick (~30 min / ~67M rows).
* Each past window's SF is deterministic and unchanged, so the recompute is pure waste; `--start` must stay `2025-01-01` or history is silently deleted.
* Independent of the model refactor (`0094-refactor-model/`); do first — it makes a fresh, cheap map feasible (a prerequisite for `0094-refactor-model/0002-shared-sf-fit`).

## Approach

* Work in: `compute/sf/persist.py` (`delete_sf_run`, `copy_sf_rows`, `write_window_meta`), `compute/sf/runner.py`, `ops/deploy/jobs/map_refresh_cronjob.yml`.
* Entry point / primary change: `compute/sf/runner.py` boundary loop.
* Query existing `sf_window_meta.window_start` for the run; compute only boundaries in the grid but absent from that set.
* Upsert per window: `INSERT ... ON CONFLICT (run_id, window_start, constraint_key, settlement_point) DO UPDATE` on `implied_shift_factors`; `ON CONFLICT (run_id, window_start)` on `sf_window_meta`.
* Keep old behavior behind an explicit `--rebuild` flag (calls `delete_sf_run` then full write).
* Update the cronjob: drop the `--start`-footgun / full-re-run comments; `--start` is now just the series origin.
* Do NOT touch: `fit.py` math, `eval.py` metrics logic, the μ pipeline.

## Acceptance

* [ ] A second run at a later `--end` fits only the new boundaries; pre-existing `implied_shift_factors` rows are byte-identical (unchanged).
* [ ] A narrow `--start` does not delete earlier windows; `--rebuild` restores the full-wipe path.
* [ ] `implied_shift_factors` + `sf_window_meta` upsert idempotently per `window_start`; re-running one boundary replaces, not duplicates.
* [ ] `geo_persist` + `eval` still resolve the newest window; API serves `max(window_start)`.
* [ ] `pytest` green.
