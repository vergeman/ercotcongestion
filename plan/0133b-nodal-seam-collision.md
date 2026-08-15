# 0133b - nodal-seam-collision

Type: fix
Branch: fix/0133b-nodal-seam-collision

## Goal

* Fix `nodal_to_db`'s single-day delete so a re-backfilled CT day can never
  collide with a stale pre-cutover row for the same hour.

## Context

* Live production crash during the 0133 rollout backfill: `UniqueViolation` on
  `forecast_nodal_pkey`, `(run_id, ts, settlement_point, horizon)` already exists.
* `nodal_to_db` deleted by the stored `delivery_date` column before COPY-ing.
  The real primary key is `(run_id, ts, settlement_point, horizon)` — no
  `delivery_date` in it. For the ~5 CT-evening seam hours per day, a `ts`'s
  `delivery_date` label differs depending on which convention wrote the row
  (old UTC-day vs. new CT-day, 0133), so a delivery_date-scoped delete misses
  the stale row and the COPY collides with it on the real key instead of
  replacing it.
* Blocks every backfilled day whose block overlaps a not-yet-reprocessed
  adjacent day still holding pre-cutover rows — i.e. most of the backfill.

## Approach

* Work in: `compute/jobs/backfill_nodal.py`
* Entry point: `nodal_to_db`
* Delete by the exact `ts` window (`ct_day_bounds(delivery_date)`) instead of
  the `delivery_date` column — correct regardless of what label any existing
  row for that `ts` currently carries, and a no-op once every day has been
  reprocessed under one convention.
* Do NOT touch: `sf_artifact_to_db` / `persist_rollup` — both upsert on
  `(run_id, delivery_date, horizon[, constraint_key])`, i.e. delivery_date is
  itself the value being written, not a derived label that can go stale at
  hour granularity. Checked, unaffected.

## Acceptance

* [x] A stale, differently-labeled row at a seam `ts` is replaced, not
      collided with, when its owning CT day is (re)written
      (`test_seam_hour_from_a_pre_cutover_row_is_replaced_not_collided` — first
      reproduces the exact production `UniqueViolation`, then passes clean).
* [x] Existing single-day-scope and idempotency tests unchanged.
