# 0076 - remove-basis-and-fragility

Type: chore
Branch: chore/0076-remove-basis-and-fragility

## Goal

* Remove the `basis` feature end-to-end (compute → DB → API → web UI).
* Remove the retired `fragility` columns that are still being written as NULL.
* Drop the associated schema (`bus_snapshots.basis`, `bus_snapshots.fragility`, `snapshot_meta.fragility_total/top10_share`, `bus_load_zones`) in a new migration once nothing reads them.

## Context

* `basis` (bus_lmp − zonal_lmp) has one live UI consumer: the DetailCard "Basis" row. Everything else in the pipeline is scaffolding that we no longer trust as a headline metric (see `compute/Basis.md` — West high-wind bias, structural narrative superseded).
* `fragility` was already retired: `compute/write_snapshots.py` writes `None` into `fragility*` columns, no API/model/web surface exists, and `api/tests/*` assert its absence. Migration `18_congestion_metrics.sql:8` promised a "Migration B will drop them" that never landed.
* Unrelated: PCA "basis" terminology in `compute/mapping/**`, `compute/clustering/**`, `compute/run_pipeline.py`, and the prose in `web/src/lib/events.ts:81` — leave alone.
* `ercot_zonal_lmp[_hourly]` tables stay: used by `compute/operating_data_adapter.py` for OPF operating data. Only `bus_load_zones` is droppable.

## Approach

Work in five commits, each self-contained and independently revertable. Land in this order so no live consumer references a column before it's dropped.

### Commit 1 — web UI: remove Basis row and field

* Work in: `web/src/`
* `web/src/components/map/DetailCard.tsx:93-99` — delete the "Basis" `<Row>` block.
* `web/src/api/types.ts:6` — remove `basis: number | null` from `BusState`.
* `web/src/App.tsx:298, 311, 325` — remove `basis: null` from the synthesized ERCOT `BusState` literals.
* Do NOT touch: PCA/basis mentions in `web/src/lib/events.ts`.
* Verify: `npm run build` (or the repo's typecheck script) passes; hover card renders without a Basis row.

### Commit 2 — API: drop basis from schema and query surface

* Work in: `api/`
* `api/models.py:16` — remove `basis: float | None` from `BusState`.
* `api/state.py:65, 121` — remove `basis` from the SELECT column lists in `/state` and `/state_range`.
* `api/tests/test_integration.py:8, 24, 33` — drop the basis-populated assertions.
* Do NOT touch: fragility-absence assertions in `test_openapi.py` / `test_state.py` / `test_integration.py:55, 69` yet — they still guard against regressions until the columns actually go away in commit 5.
* Verify: `pytest api/tests` green; `/state` OpenAPI no longer lists `basis`.

### Commit 3 — compute: stop writing basis and fragility

* Work in: `compute/`
* `compute/snapshot.py` — remove `_compute_basis` and the `basis`, `basis_n_resolved`, `basis_abs_mean` result keys/diagnostics (lines 209, 240-241, 255, 276-295).
* `compute/write_snapshots.py` — remove `basis` and every `fragility*` name from the UPSERT column lists, tuple values, and comments (lines 77-91, 98, 134-135, 172, 183-194, 268-269, 309).
* `compute/sample_specs/extract_dates.py:61-62, 70` — remove the `fragility_total` SELECT clause (or delete the file if unused elsewhere; grep first).
* `compute/README.md:8`, `compute/snapshot.md:295` — remove basis mentions.
* Do NOT touch: `compute/mapping/**`, `compute/clustering/**`, `compute/run_pipeline.py` (unrelated PCA basis).
* Verify: run one snapshot end-to-end; `bus_snapshots` insert succeeds with the reduced column list; no NULL fragility writes remain.

### Commit 4 — delete dead files and ops

* Delete: `compute/backill_basis.py`, `compute/Basis.md`, `db/job_queries/backfill_basis.sql`, `ops/deploy/jobs/backfill_basis_job.yml`, `fragility_map.png`.
* Edit: `ops/deploy/backfills.sh:50, 55` — remove the `backfill-basis` job invocation and any surrounding menu/dispatch entry.
* Verify: `grep -rIn 'backfill_basis\|backill_basis\|fragility_map' .` returns nothing outside git history.

### Commit 5 — new DB migration: drop columns and table

* Work in: `db/migrations/`
* Add `db/migrations/NN_drop_basis_and_fragility.sql`:
  * `DROP INDEX IF EXISTS bus_snapshots_basis_idx;`
  * `DROP INDEX IF EXISTS bus_snapshots_fragility_idx;`
  * `ALTER TABLE bus_snapshots DROP COLUMN IF EXISTS basis;`
  * `ALTER TABLE bus_snapshots DROP COLUMN IF EXISTS fragility;`
  * `ALTER TABLE snapshot_meta DROP COLUMN IF EXISTS fragility_total;`
  * `ALTER TABLE snapshot_meta DROP COLUMN IF EXISTS fragility_top10_share;`
  * `DROP TABLE IF EXISTS bus_load_zones;`
* Remove the fragility-absence assertions in `api/tests/test_openapi.py`, `api/tests/test_state.py`, `api/tests/test_integration.py:55, 69` (they've now served their purpose).
* Do NOT touch: `db/migrations/07_snapshots.sql`, `09_basis.sql`, `18_congestion_metrics.sql` — those are historical; the new migration supersedes them.
* Verify: `psql \d bus_snapshots` and `\d snapshot_meta` no longer list the dropped columns; `pytest api/tests` still green.

## Acceptance

* [ ] Web build succeeds; DetailCard no longer shows Basis; no `basis` field in `BusState` type.
* [ ] `/state` and `/state_range` OpenAPI schemas contain no `basis` field; `pytest api/tests` green.
* [ ] `compute/snapshot.py` and `compute/write_snapshots.py` contain no reference to `basis` or `fragility`; a fresh snapshot writes cleanly.
* [ ] `grep -rIn 'basis\|fragility' compute/ api/ web/ ops/ db/` returns only unrelated PCA/prose matches called out in Context.
* [ ] New migration runs cleanly on a snapshot DB; `bus_snapshots.basis`, `bus_snapshots.fragility`, `snapshot_meta.fragility_total`, `snapshot_meta.fragility_top10_share`, and table `bus_load_zones` are gone.
* [ ] `ercot_zonal_lmp` and `ercot_zonal_lmp_hourly` are untouched; OPF operating-data path still works.
