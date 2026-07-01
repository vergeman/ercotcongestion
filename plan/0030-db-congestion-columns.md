# B2 - db-congestion-columns

Type: feat
Branch: feat/db-congestion-columns

## Goal

* Add `modeled_congestion`, `binding_proximity` to `bus_snapshots` and the five new meta columns to `snapshot_meta`.
* Update `compute/write_snapshots.py` to populate the new columns and NULL the old `fragility*` columns on new writes.
* Add `--force-recompute` flag so recomputes overwrite existing `status='ok'` rows.

## Context

* Depends on B1 (`refactor/rename-congestion-metrics`) - result dict must already carry the new keys.
* Migration tooling is hand-rolled numbered SQL under `db/migrations/NN_name.sql`. Next unused number: check `ls db/migrations/` (last was `17_timestamp_correction.sql`).
* Decision (locked): NULL the old `fragility` columns on new writes rather than dual-computing. Rollback path is `git revert` + rerun. See sprint2a-plan.md §3.6.
* Migration B (drop old columns) is out of scope - happens after 2B + 2C ship.

## Approach

* Work in: `db/migrations/`, `compute/write_snapshots.py`
* Add `db/migrations/18_congestion_metrics.sql`:
  * `ALTER TABLE bus_snapshots ADD COLUMN modeled_congestion double precision, ADD COLUMN binding_proximity double precision;`
  * `ALTER TABLE snapshot_meta ADD COLUMN modeled_congestion_total/abs_total/top10_share double precision, ADD COLUMN binding_proximity_max/p95 double precision;`
* Update `compute/write_snapshots.py`:
  * `UPSERT_BUS_SNAPSHOT_SQL` (lines 64-71): add both new columns to insert list, placeholders, and `ON CONFLICT DO UPDATE SET`. Retain `fragility` column write (NULL).
  * `UPSERT_META_SQL` (lines 73-115): add the five new meta columns; retain old three (NULL).
  * `write_snapshot()` (lines 127-191): read `mc = result['modeled_congestion']`, `bp = result['binding_proximity']`; append `_f(mc, bus_id)`, `_f(bp, bus_id)` to bus tuple; pass `None` for `fragility`. Update `meta_row` similarly.
  * `write_failure()` (lines 194-216): extend `meta_row` shape; all new columns → `None`.
* Add `--force-recompute` CLI flag (or `--no-skip-existing`) so recompute UPSERTs overwrite `status='ok'` rows.
* Do NOT drop old columns. Do NOT touch API/frontend. Do NOT trigger a full recompute here.

## Acceptance

* [x] Migration `18_congestion_metrics.sql` applies cleanly; new columns exist and default to NULL on existing rows.
* [x] A single-snapshot run of `write_snapshots.py` populates all new columns on the affected row and writes NULL for `fragility*`.
* [x] `write_failure()` writes a row with NULL new columns and does not error on the extended schema.
* [x] `--force-recompute` overwrites an existing `status='ok'` row (verify via updated `binding_proximity_max`).
* [x] No `fragility_total` / `fragility_top10_share` values written by new code (SELECT confirms NULL after new writes).
