# 0077 - remove-ercot-rt-lmp

Type: chore
Branch: chore/0077-remove-ercot-rt-lmp

## Goal

* Remove all ingestion code paths that write to `ercot_rt_lmp`.
* Remove `ercot_rt_lmp` from operational/export tooling and docs.
* Drop the `ercot_rt_lmp` table via a new migration.

## Context

* `ercot_rt_lmp` (NP6-788-CD, RT LMPs at Settlement Points) is ingested but has
  zero downstream consumers — no references in `compute/`, `web/`, or `api/`.
* `17_timestamp_correction.sql` is a historical, sentinel-guarded migration
  already applied in prod — left unmodified.
* Follows the pattern set by `db/migrations/23_drop_basis_and_fragility.sql`
  (plan 0076).

## Commits

1. **Ingest pipeline** (`9577e25`) — removed `rt_lmp` from `ENDPOINTS` in
   `backfill.py`, deleted `load_rt_lmp()` from `loaders.py`, removed the
   fetch/load/print calls from `ErcotClient.py`.
2. **Table drop** (`796ec42`) — added
   `db/migrations/24_drop_rt_lmp.sql` (`DROP TABLE IF EXISTS ercot_rt_lmp`).
3. **Ops/docs cleanup** (`6cc4ccc`) — removed `ercot_rt_lmp` from
   `db/export_prod_database.sh`, the frequency table in
   `ercot_ingest/README.md`, and the informational comment in
   `ops/deploy/jobs/backfill_ingest_job.yml`.

## Acceptance

* [x] `grep -rn "rt_lmp" ercot_ingest/ db/export_prod_database.sh` returns no
      matches.
* [x] `db/migrations/14_rt_lmp.sql` and `17_timestamp_correction.sql` remain
      unmodified.
* [x] New migration `24_drop_rt_lmp.sql` added, following the
      `23_drop_basis_and_fragility.sql` pattern.
* [x] `ast.parse` succeeds on `backfill.py`, `loaders.py`, `ErcotClient.py`.
* [x] `live_updater.py` unaffected (imports `ENDPOINTS`/`backfill_one_window`
      only, no direct `rt_lmp` reference).
