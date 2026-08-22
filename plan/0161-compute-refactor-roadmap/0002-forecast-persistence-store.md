# 0161-0002 - Extract forecast persistence store

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap/0002-forecast-persistence-store

## Goal

* Move forecast-panel, artifact, and current-pointer DB operations out of the backfill job.
* Preserve transactional ordering and idempotent replacement exactly.

## Context

* `daily_forecast` imports persistence functions from `backfill_nodal`, making an offline runner the owner of shared production writes.
* The publication contract is ordered: write nodal rows, write artifact, move pointer, then commit.

## Approach

* Work in: new `compute/forecast_store.py`, `compute/jobs/backfill_nodal.py`, `compute/jobs/daily_forecast.py`.
* Move `nodal_to_db`, artifact upsert/persistence, and pointer upsert into the store without changing signatures or SQL.
* Keep temporary compatibility re-exports from `backfill_nodal` until every caller and test uses the neutral module.
* Add focused store tests for CT-day delete scope, horizon scope, COPY rows, and pointer-last behavior using existing fakes/fixtures.
* Do NOT move transaction ownership: callers continue to commit or roll back.

## Acceptance

* [ ] Daily publish and bulk backfill follow the same SQL/write order as before.
* [ ] Horizon-1 and horizon-2 replacement remain isolated.
* [ ] `test_forecast_day.py`, `test_propagate.py`, and `test_backfill_nodal.py` pass.

## Suggested regression tests

* Use a recording fake connection/cursor to assert the daily path issues operations in the exact order: delete/COPY nodal rows, upsert SF+μ artifact, upsert pointer, then one commit.
* Seed h1, h2, and legacy UTC-labeled rows for adjacent CT dates; republish one CT day and assert only the intended timestamp window and horizon are replaced.
* Run the existing disposable-Postgres integration fixture for both a single-day publish and a multi-day bulk seed; compare row counts, PK uniqueness, artifact bytes, and promoted run ID.
