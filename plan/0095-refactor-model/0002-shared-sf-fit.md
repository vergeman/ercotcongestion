# 0002 - shared-sf-fit

Type: refactor
Branch: refactor/0094-0002-shared-sf-fit

## Goal

* Have the daily forecast consume the map's persisted weekly SF (`implied_shift_factors`, `map-v1`) instead of refitting SF on `[D−240, D)` every day.
* Add a freshness/coverage guard so a stale or missing map SF fails loud (prior pointer intact), never silently serves stale geography.
* Route the backfill/backtest through the same persisted-SF source so historic == live (closes the cadence seam).

## Context

* `forecast_day` refits SF daily; the map fits the same SF weekly and persists it — overlapping windows are duplicate compute (README "known redundancies").
* The model already assumes SF stationary within the 7-day refit interval, so the latest weekly SF is valid for D (≤6 days old).
* Introduces a forecast→map dependency; depends on `0092-map-revizualization/0092-sf-incremental-append` (cheap/fresh map) and `0001-library-runner-split` (this dir). Weighs staleness/coupling against killing the duplicate fit — see `plan/pending-research.md`.

## Approach

* Work in: `compute/jobs/daily_forecast.py`, `compute/jobs/backfill_nodal.py`, `compute/sf/project.py` (all post-`0001-library-runner-split`).
* Entry point / primary change: the SF-load step replacing `implied_shift_factors` in the forecast path.
* Load the latest `map-v1` window (`max(window_start)`) from `implied_shift_factors`; project μ through it via `compute/sf/project.py` — drop the in-forecast `implied_shift_factors` call.
* Guard: latest `window_start` within N days of D, non-empty SF, coverage over D's constraint universe above a floor; else raise (keep pointer).
* Still write `forecast_sf_artifact` per `(run_id, delivery_date)` from the loaded SF.
* Backfill uses the same persisted-SF read so a historic day matches the live path.
* Do NOT touch: `fit.py` math; the μ heads; the map runner's own fit.

## Acceptance

* [x] The forecast path issues no `implied_shift_factors` call: `daily_forecast` calls `load_forecast_sf` (reads the latest causal `map-v1` window from `implied_shift_factors`) and passes it into `propagate_window(sf=…)`; the in-forecast fit is gone. `backfill_nodal` reads the same source per week (`--fit-sf` restores the old fit).
* [x] Missing / stale (`D − window_end > MAX_SF_AGE_DAYS = 14`) / empty / `< MIN_SF_COVERAGE = 0.5` coverage all raise before any write, so the prior `forecast_current[ercot]` stays intact. All four modes unit-tested (`test_load_forecast_sf_fails_loud_on_missing_stale_empty_or_low_coverage`).
* [x] `forecast_sf_artifact` still written per `(run_id, delivery_date)` — from the loaded SF now (`persist_forecast` unchanged).
* [ ] Nodal-output-vs-prior-daily-refit spot check on a real day within tolerance — **not run here** (needs the live DB + a built `map-v1`). Code path is unit-tested; the numeric comparison is a prod-side follow-up.
* [x] `pytest` green — full compute suite 223 passed, 1 skipped.

## Follow-ups / open

* Validate the `MAX_SF_AGE_DAYS=14` / `MIN_SF_COVERAGE=0.5` floors against real `implied_shift_factors` overlap before they gate production (a too-high coverage floor causes false forecast outages). Both are CLI-overridable (`--max-sf-age-days`, `--min-sf-coverage`).
* Run the spot-day nodal comparison (persisted-SF vs `--fit-sf`) on the prod DB and record the tolerance.
