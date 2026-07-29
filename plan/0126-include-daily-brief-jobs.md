# 0126 - include-daily-brief-jobs

Type: feat
Branch: feat/0126-include-daily-brief-jobs

## Goal

* Chain `compute_brief` into `daily_forecast` so every `--to-db` tick publishes the day's brief in-process (and re-briefs the just-graded day so F6 after-action fills).
* Add `compute/jobs/backfill_briefs.py` to brief a date range from already-written artifacts — cheap, no refit.
* Keep both non-fatal / idempotent, horizon-scoped, and manifest-free (the existing forecast cronjobs pick them up unchanged).

## Context

* 0124 shipped the brief engine + `compute/jobs/daily_brief.py` + `GET /analysis/brief`, but nothing scheduled the job (as-built: "Not wired") — served history has artifacts, no briefs.
* `daily_forecast` runs twice daily (h1 final + h2 preview cronjobs) and already folds `grade_day` into the same tick via `_grade_latest`; the brief must be horizon-scoped the same way.
* `analysis_brief` is keyed `(run_id, delivery_date, horizon)`; the serving endpoint coalesces to `min(horizon)` (final when present, else preview). Migration `38_analysis_brief.sql` must exist wherever these run.

## Approach

### Commit 1 — brief in the daily tick

* Work in: `compute/jobs/daily_forecast.py`
* Entry point / primary change: `main()` post-publish chain + new `_brief_latest`
* Import `compute_brief, persist_brief` from `compute.jobs.daily_brief` (no cycle — `daily_brief` never imports `daily_forecast`).
* Make `_grade_latest` **return** the graded `pd.Timestamp | None` (was `None`), so the brief step can re-brief that day for after-action.
* Add `_brief_latest(conn, run_id, published, horizon, graded=None)`: two horizon-scoped upserts — the day just **published** (forward, forecast basis) and the day just **graded** (F6 after-action, skipped if equal to published). Non-fatal like `_grade_latest`; each day its own transaction.
* Wire it into `main()` right after `_grade_latest`, gated by a new `--no-brief` flag (symmetric with `--no-grade`).
* Key on the tick's exact `(run_id, D, args.horizon)` — NEVER `resolve_briefable_date`, whose horizon-agnostic self-selection lets one track mark a day done and starve the other.
* Do NOT touch: the fit / modeling path; the cronjob manifests (both already run `daily_forecast`).

### Commit 2 — backfill_briefs.py

* Work in: `compute/jobs/backfill_briefs.py` (new module)
* Entry point / primary change: `main()` — range loop mirroring `backfill_artifacts` scaffolding
* Brief only days that already have a `forecast_sf_artifact`; skip days already in `analysis_brief` (`--no-skip-existing` rewrites); days with no artifact are counted, not errored.
* Per day: resolve horizon via `_served_horizon` (or `--horizon`), then `compute_brief` + `persist_brief`. CHEAP — one artifact-blob read + re-rank, **no refit**; F6 fills for days whose DAM has landed.
* One warm connection for the whole run (briefs are seconds of frequent DB traffic — no idle-drop like the per-day refit). Fail-soft (`--stop-on-error` aborts); dry-run unless `--to-db`.
* Do NOT: refit anything; touch `backfill_artifacts.py` (this is its read-side companion).

## Acceptance

Verified against the served `mu-all-v1` June-30 artifact in the dev stack.

* [x] `daily_forecast --to-db` chains `_brief_latest` after `_grade_latest`; briefs the published day + re-briefs the graded day, both keyed `(run_id, delivery_date, args.horizon)`. — `daily_forecast.py`
* [x] `_grade_latest` returns the graded date; `_brief_latest` and the whole chain are non-fatal (a brief failure never fails the publish or moves the pointer).
* [x] `--no-brief` flag present and skips the brief step (symmetric with `--no-grade`). — CLI help
* [x] `backfill_briefs.py` briefs a range from existing artifacts with no refit; resumable skip of already-briefed days; `--no-skip-existing` rewrites. — run against dev DB (1 skipped-existing, 4 no-artifact, 0 todo)
* [x] No-artifact days are counted + skipped, not errored; `--horizon 2` (absent) → no-artifact, `--horizon 1` (present) → briefed. — dev DB
* [x] Rewrite is idempotent — brief JSON byte-identical across a re-run (`computed_at` aside). — sha256 unchanged before/after
* [x] F6 after-action fills on backfill for days whose DAM exists (`after_action=True`, 2026-06-30). — job log

### As-built notes

* No k8s manifest change — both `ops/deploy/jobs/forecast_cronjob.yml` (h1) and `forecast_preview_cronjob.yml` (h2) already invoke `daily_forecast`, so the brief ships with the next image roll.
* `--no-brief` and `--no-grade` are independent; a forecast-only backfill can set either.
* The single-day `python -m compute.jobs.daily_brief` CLI (0124) remains for one-offs; `backfill_briefs.py` is the range tool.
