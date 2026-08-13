# 0129-0004 - forecast-history-rollup

Type: feat
Branch: feat/0129-0004-forecast-history-rollup
Depends on: `0002` (widens its magnitude slot)

## Goal

* Roll daily forecast Σμ per constraint out of `forecast_sf_artifact.E_mu` into a
  queryable daily series, backfilled over existing artifact history.
* Let Standouts and the hero rank today's forecast against a window of past
  **forecasts** instead of past settles.
* Replace `0002`'s forecast-against-settled historical comparison with a
  forecast-against-forecast comparison over the same artifact-key vocabulary.

## Context

* The prototype's data-status table calls this `mock` — *"nothing persists what was
  forecast for a past delivery day."* **That is wrong as stated.**
  `forecast_sf_artifact` persists `E_mu` (hours × constraints, forecast μ, untruncated)
  per `(run_id, delivery_date, horizon)`, decoded by
  `compute/sf/project.py::load_sf_mu` and already loaded by
  `compute/jobs/daily_brief.py::_load_artifact`. The history exists; it is not
  conveniently queryable as a daily series.
* Why it matters: ranking a forecast Σμ inside a distribution of *settled* Σμ is the
  weakness `docs/daily_brief_v6_prototype.html:1138` documents — the forecast runs low,
  so the test under-fires. `0002` works around it by restricting both sides to the cast
  keys, which is honest but narrows the window.
* Cost shape: this is a per-day blob decode. A 365-day rollup means 365 decodes, so it
  wants to be a materialized table written once and appended daily, not an on-demand
  aggregate — the opposite of the query-first default everywhere else in `0129`, and
  the reason is the blob, not the arithmetic.

## Approach

* Work in: `compute/jobs/`, `db/migrations/`, `compute/analysis/hero_window.py`
* New table keyed like the artifact it derives from —
  `(run_id, delivery_date, horizon, constraint_key)` carrying daily Σμ and binding
  hours. Same idempotency scope as `forecast_sf_artifact`, upsert in place, so a re-run
  replaces a day.
* Populate two ways: a backfill job over existing artifact days, and an append in the
  daily tick. The append belongs next to `_brief_latest` in
  `compute/jobs/daily_forecast.py` and must be **non-fatal by contract** like its
  neighbours — the forecast is already published and committed by then, so a rollup
  failure must not fail the publish or move the pointer.
* Roll up the **untruncated** `E_mu`, not the cast. The whole point is to have a
  forecast number for constraints below the serving floor, which is also what `0005`
  serves from the other direction.
* Then update `0002`'s magnitude slot: rank forecast against forecast over
  `artifact_keys`, and keep `basis` on the response so the change is visible
  rather than silent.
* Do NOT touch: the artifact itself, `build_brief`, or the fit.

## Acceptance

* [ ] Backfill produces one row per (day, constraint) over available artifact history; row count matches `n_constraints` per day, not the cast size.
* [ ] The daily tick appends the published day, and a failure there leaves the forecast published (test by forcing an exception).
* [ ] `0002`'s magnitude slot reports an explicit forecast-history basis over
  `artifact_keys`, with a forecast-vs-forecast rank.
* [ ] Re-running the backfill for a day is a no-op on the row count.
* [ ] A day whose artifact is missing is skipped with a log line, not a crash.
