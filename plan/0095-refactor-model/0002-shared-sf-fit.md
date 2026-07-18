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

* [ ] The forecast path issues no `implied_shift_factors` call; it reads persisted weekly SF and projects.
* [ ] A missing / stale (> N days) / low-coverage map SF fails loud with the prior `forecast_current[ercot]` intact.
* [ ] `forecast_sf_artifact` still written per `(run_id, delivery_date)`.
* [ ] Nodal output matches the prior daily-refit output on a spot day within a documented tolerance.
* [ ] `pytest` green.
