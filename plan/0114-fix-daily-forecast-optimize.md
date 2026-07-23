# 0005 - live-grade-selector-performance

Type: fix
Branch: fix/0014-fix-daily-forecast-optimize

## Goal

* Make the daily tick select a gradeable day without scanning historical nodal forecasts.
* Preserve the requirement that a selected day is fully realized.
* Log selector and grading boundaries for operational diagnosis.

## Context

* Production's `resolve_gradeable_date()` ran for hours in `DataFileRead` after a successful forecast publish.
* Its correlated `MAX(ts)` uses `forecast_nodal_pkey (run_id, ts, settlement_point)` and filters by `delivery_date`.
* `forecast_nodal` has ~22.5M rows; the existing `(run_id, delivery_date)` index cannot serve that maximum.

## Approach

* Work in: `compute/jobs/grade_day.py`, `compute/jobs/daily_forecast.py`, `db/migrations/`.
* Entry point / primary change: `resolve_gradeable_date()`.
* Select ungraded forecast dates newest-first and test the expected final UTC hour (`D + 23h`) in `dam_system_lambda`; do not calculate `MAX(ts)` from `forecast_nodal`.
* Add timing/start-end logs around selection and `grade_day()`.
* Add a regression test for the selector query shape. No new index is needed: the existing `(run_id, delivery_date)` index enumerates candidate days, and the slow per-day timestamp aggregate is removed rather than optimized.
* Do NOT touch: score definitions, forecast publication order, or scoreboard API contracts.

## Acceptance

* [ ] Production selector completes promptly on the current `forecast_nodal` history and has no broad timestamp scan. (Implementation removes the scan; production query-plan/runtime verification remains.)
* [x] It returns only an ungraded day whose final UTC hour has realized system lambda.
* [x] Tests cover no candidate, partial realization, and newest gradeable-day selection.
* [x] Logs distinguish selection time from grading time.
