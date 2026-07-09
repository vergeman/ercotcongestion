# 0076 - remove-basis-and-fragility

Type: chore
Branch: chore/0076-remove-basis-and-fragility
Status: done

## Goal

Remove `basis` end-to-end (compute → DB → API → web) and the already-retired
`fragility` columns. Drop the schema (`bus_snapshots.basis/fragility`,
`snapshot_meta.fragility_total/top10_share`, `bus_load_zones`) once nothing
reads them.

## Context

* `basis` (bus_lmp − zonal_lmp) had one live consumer: DetailCard's "Basis"
  row. Rest of the pipeline was scaffolding no longer trusted as a headline
  metric (see deleted `compute/Basis.md`).
* `fragility` was already dead: written as `None`, no API/web surface,
  tests assert its absence. `18_congestion_metrics.sql` deferred the drop
  to a "Migration B" that never landed — this is it.
* Left alone: PCA "basis" terminology (`compute/mapping/**`,
  `compute/clustering/**`), `web/src/lib/events.ts:81` prose,
  `ercot_zonal_lmp[_hourly]` (used by `operating_data_adapter.py`).

## Commits (landed in order, each revertable)

1. **web** — removed Basis row/field (`DetailCard.tsx`, `api/types.ts`,
   `App.tsx`, dead `--basis-*` CSS vars).
2. **API** — dropped `basis` from `BusState` and the `/state`,
   `/state_range` SELECT lists.
3. **compute** — removed `_compute_basis` and basis/fragility writes from
   `snapshot.py`, `write_snapshots.py`; dropped `fragility_total` from
   `extract_dates.py`'s regime query; doc cleanup.
4. **cleanup** — deleted `backill_basis.py`, `Basis.md`,
   `backfill_basis.sql`, `backfill_basis_job.yml`, `fragility_map.png`;
   trimmed `ops/deploy/backfills.sh`.
5. **migration** — `db/migrations/23_drop_basis_and_fragility.sql` drops
   the columns/indexes/table; removed the now-obsolete fragility-absence
   test assertions.

Also pruned other historical docs referencing the retired metrics:
deleted `compute/rank.md` (documented a UI view that no longer exists),
reworded passing mentions in `N1.md`/`opf.md`. Left
`compute/experiments/derate_sweep/**` in place (it's the empirical record
behind the live derate=1.00/1.00 setting) but inlined a local
`_compute_basis` there since it imported the now-deleted `snapshot.py` one.

## Acceptance

* [x] Web build has no `basis` field/row (build itself blocked by a
  pre-existing unrelated missing dep, `@cloudflare/vite-plugin`).
* [x] `/state`, `/state_range` OpenAPI has no `basis`; `pytest api/tests` green.
* [x] Fresh snapshot write leaves `basis`/`fragility*` NULL; verified end-to-end.
* [x] Repo-wide grep clean outside noted exceptions.
* [x] Migration applied cleanly on dev DB; columns/table confirmed gone.
* [x] `ercot_zonal_lmp[_hourly]` and OPF operating-data path untouched/working.
