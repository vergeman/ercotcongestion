# 0080 - dam-system-lambda-stat

Type: feat
Branch: feat/0080-dam-system-lambda-stat

## Goal

* Surface ERCOT's published DAM system lambda (`dam_system_lambda.system_lambda`) as a new field on `SnapshotMeta`, joined per-hour at request time.
* Display it as a new stat in StatsPanel's "System State" section, alongside `Obj Cost`.
* No migration, backfill, or offline-pipeline change required — `dam_system_lambda` is already fully ingested (`ercot_ingest/loaders.py`, backfilled historically).

## Context

* `dam_system_lambda` (`db/migrations/13_dam_lambda.sql`) is ERCOT's NP4-523-CD report: one system-wide $/MWh value per hour, keyed `(interval_ts, dst_flag)`. It's already live-ingested and backfilled — nothing to add on the ingestion side.
* `snapshot_meta` already carries **model-computed** lambda estimates (`system_lambda_kkt`, `system_lambda_merit_order` from `db/migrations/19_opf_persistence.sql`), written by the offline OPF pipeline (`compute/write_snapshots.py`). ERCOT's published lambda is a distinct, independently-sourced ground-truth value — baking it into `snapshot_meta` would require joining it into that pipeline for no benefit, since the table is already keyed on the same `interval_ts` grain and fully populated on its own.
* `api/state.py`'s `get_state`/`get_state_range` currently do `SELECT * FROM snapshot_meta` and splat rows straight into the `SnapshotMeta` pydantic model — extra dict keys not declared on the model are just ignored, and missing keys fall back to `None` defaults. This makes a live join at request time (rather than a schema migration) the lowest-risk path.
* Existing dedup idiom for `dam_system_lambda`'s DST-doubled rows, used consistently in `compute/regimes/covariates.py:131-146`, `compute/implied_binding_proximity/panels.py:99-108`, `compute/ercot/transforms.py:128-142`: `SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda FROM dam_system_lambda WHERE interval_ts = ANY(%s) ORDER BY interval_ts, dst_flag ASC`.

## Commit 1 — backend: join dam_system_lambda into /state and /state_range

* Work in: `api/state.py`, `api/models.py`
* Entry point / primary change: `get_state`, `get_state_range` in `api/state.py`
* Add `dam_system_lambda: float | None = None` to `SnapshotMeta` in `api/models.py`, placed near `objective_cost` since it's a scalar system-wide $/MWh value.
* In `get_state`: after fetching `meta_row`, run a second query `SELECT system_lambda FROM dam_system_lambda WHERE interval_ts = %s AND dst_flag = FALSE` and merge the value into `meta_row` (as `dam_system_lambda`) before constructing `SnapshotMeta(**meta_row)`. Use `dst_flag = FALSE` directly (equivalent to the `ORDER BY dst_flag ASC` idiom for a single-row lookup) rather than `DISTINCT ON`, since there's exactly one timestamp.
* In `get_state_range`: add one batched query `SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda FROM dam_system_lambda WHERE interval_ts >= %s AND interval_ts < %s ORDER BY interval_ts, dst_flag ASC`, build a `dict[datetime, float]` keyed by `interval_ts` (mirroring the existing `bus_by_ts` grouping pattern at lines 139-142), and merge into each `meta_row` dict before constructing `SnapshotMeta(**row)`.
* Do NOT touch: `snapshot_meta` table schema, `compute/write_snapshots.py`, any migration file — `dam_system_lambda` stays a separate table, joined only at the API layer.

## Commit 2 — frontend: type + StatsPanel display

* Work in: `web/src/api/types.ts`, `web/src/components/panels/StatsPanel.tsx`
* Entry point / primary change: `SnapshotMeta` interface, `StatsPanel`'s "System State" section
* Add `dam_system_lambda: number | null;` to `SnapshotMeta` in `types.ts`, matching the new backend field name and position.
* In `StatsPanel.tsx`, add a `<Stat>` row for it in the "System State" section (around the existing `Obj Cost` stat, `StatsPanel.tsx:96-103`), formatted as `$/MWh` via the existing `fmt()` helper: `` `$${fmt(meta.dam_system_lambda, 2)}/MWh` ``. Use 2 decimals (lambda values are typically small $/MWh, unlike the large `Obj Cost` totals which use 0 decimals).
* Do NOT touch: the Model/Cluster Correlation sections, scorecard rows, or any styling beyond adding the one stat row — this is an additive display change only.

## Commit 3 — tests

* Work in: `api/tests/test_state.py`
* Entry point / primary change: `_meta_row` fixture helper and the two `/state`, `/state_range` tests
* Update `fake_pool.cursor.queue(...)` call sequences in `test_state_returns_meta_and_buses` and `test_state_range_groups_buses_per_snapshot` to include the new `dam_system_lambda` lookup query's result set (one extra `cursor.queue([...])` call per test, matching the new query added in Commit 1).
* Assert `data['meta']['dam_system_lambda']` is present and equals the queued value in both tests.
* Do NOT touch: `test_openapi.py` — the schema regression guard only asserts a subset of required fields are present, so no update is needed there, but running it after Commit 1 is still a fast repeat-nothing-broke check.

## Acceptance

* [ ] `GET /api/state?t=...` response includes `meta.dam_system_lambda` as a float (or `null` if no matching hourly row).
* [ ] `GET /api/state_range?start=...&end=...` includes `meta.dam_system_lambda` per entry, correctly aligned to each entry's `interval_ts` (verify against a known multi-hour window spanning at least one DST-flagged date if available).
* [ ] StatsPanel's "System State" section renders a new stat showing the DAM system lambda in `$/MWh`, falling back to `—` when null.
* [ ] `api/tests/test_state.py` passes with the new field asserted in both `/state` and `/state_range` tests.
* [ ] No changes to `snapshot_meta` schema, migrations, or `compute/write_snapshots.py`.
