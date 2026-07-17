# 0093-0005 - sf-incremental-append

Type: refactor
Branch: refactor/0093-0005-sf-incremental-append

## Goal

* Replace the map runner's delete-all-then-rewrite with per-window append: a run
  fits and persists only the refit boundaries it does not already have.
* Persist only COMPLETE windows (a full refit-week on the fixed grid); never the
  clamped tail — so every persisted `window_start` is immutable and the served
  window is the newest complete week.
* Drop the `--start` footgun; add `--rebuild` for an explicit full wipe + refit.

## Context

* Post-0093 the runner is SF-only: each refit fits SF and (via `on_refit_window`)
  persists `implied_shift_factors` + `sf_window_meta`. It still `delete_sf_run` then
  rewrites every window from 2025-01-01 each weekly tick — re-fitting and re-COPYing
  unchanged history (~30 min).
* `window_start` fully determines the fit (`window_end = window_start + window_days`),
  so any already-persisted boundary is byte-identical — pure waste to recompute.
* Why "complete windows only": the refit grid is anchored at a fixed past date and
  steps forward (`rolling.py`), so the terminal window's `window_end` is clamped to
  available data → an off-grid, partial `window_start` that would shift (and orphan)
  once more DAM lands. Persisting only complete windows makes every `window_start`
  final; the served map becomes the last complete week, advancing one week per run.
  The map is not time-indexed and intra-week staleness is structurally harmless, so
  the ≤`refit_days` tail lag is invisible — and a full-week fit is cleaner than the
  old partial-week one.
* `eval` keeps scoring the full weekly history (its metrics backfill onto
  `sf_window_meta` by `score_start`); this plan does not change that.
* Depends on `rolling_bp(skip_window_starts=...)` (already present from 0092).
* Downstream: makes a fresh, cheap map feasible — a prerequisite for
  `0094-refactor-model/0002-shared-sf-fit`.

## Approach

* Work in: `compute/sf/runner.py`, `compute/sf/persist.py`,
  `ops/deploy/jobs/map_refresh_cronjob.yml`.
* `persist.py`: add `existing_sf_windows(conn, run_id) -> set` (DISTINCT
  `sf_window_meta.window_start`).
* `runner.py`:
  * `--rebuild`: `delete_sf_run` then full refit + persist (today's behavior).
  * default (`--persist-sf`, no `--rebuild`): query `existing_sf_windows`; pass their
    ns-instants (`pd.Timestamp(ws).value`) as `skip_window_starts` so `rolling_bp`
    skips the fit for boundaries already persisted.
  * in `on_refit`: persist a window only if it is COMPLETE —
    `score_end - score_start == timedelta(refit_days)` (the clamped tail fails this
    and is skipped) — and (belt-and-suspenders) its `window_start` is not already
    persisted.
* Idempotency without a per-window delete: a no-`--rebuild` run only writes
  `window_start`s absent from `sf_window_meta`, so it never re-COPYs an existing
  window (no PK clash, no duplicate); `write_window_meta` upserts regardless.
  `--rebuild` wipes first. No provisional / orphan / delete-then-copy machinery is
  needed — complete windows are on the fixed grid and never re-dated.
* cronjob: drop the `FOOTGUN` / "`--start` MUST stay 2025-01-01" comments; `--start`
  is now just the series origin. Keep the weekly schedule (runs are now append-only
  and cheap); `--rebuild` is the documented full-rebuild path.
* Do NOT touch: `fit.py` math, `eval.py`, `geo_persist.py`, the μ pipeline.

## Acceptance

* [ ] A second run at a later `--end` fits + writes only the new complete boundaries;
  pre-existing `implied_shift_factors` / `sf_window_meta` rows are byte-identical.
* [ ] The clamped tail week is never persisted; `max(window_start)` is always a
  complete-week fit.
* [ ] Re-running the same `--end` is a DB no-op (all complete windows already present;
  nothing re-fit into the DB, nothing duplicated).
* [ ] `--rebuild` restores the full wipe + refit.
* [ ] `geo_persist` + `eval` still resolve the newest window; API serves `max(window_start)`.
* [ ] `pytest` green.
