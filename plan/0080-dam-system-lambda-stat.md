# 0080 - dam-system-lambda-stat

Type: feat
Branch: feat/0080-dam-system-lambda-stat

## Goal

Surface ERCOT's published DAM system lambda (`dam_system_lambda.system_lambda`) as a new `SnapshotMeta` field, joined per-hour at request time, and show it in StatsPanel's "System State" section next to `Obj Cost`. No migration/backfill — `dam_system_lambda` is already fully ingested.

## Context

* `dam_system_lambda` (`13_dam_lambda.sql`, NP4-523-CD): one $/MWh value per hour, PK `(interval_ts, dst_flag)`. Already live-ingested and backfilled.
* Kept as a separate table joined at the API layer, not baked into `snapshot_meta` — it's independently-sourced ground truth on the same `interval_ts` grain, so a migration buys nothing.
* `api/state.py` splats `SELECT * FROM snapshot_meta` rows into the `SnapshotMeta` model; extra keys are ignored, missing keys default to `None` — so a request-time join is the lowest-risk path.
* DST-doubled rows deduped with `ORDER BY dst_flag ASC` (prefer canonical `FALSE`), matching `covariates.py` / `transforms.py`.

## Commit 1 — backend: join dam_system_lambda into /state and /state_range

* Work in: `api/state.py`, `api/models.py`
* Add `dam_system_lambda: float | None = None` to `SnapshotMeta`, near `objective_cost`.
* Both endpoints add a `LEFT JOIN LATERAL` (single round trip, PK-driven lookup); matches on `interval_ts` alone so a `dst_flag = TRUE`-only hour still resolves, `ORDER BY dst_flag ASC LIMIT 1` prefers `FALSE`:
  ```sql
  LEFT JOIN LATERAL (
      SELECT system_lambda FROM dam_system_lambda d
      WHERE d.interval_ts = sm.interval_ts
      ORDER BY d.dst_flag ASC
      LIMIT 1
  ) dsl ON true
  ```
* `META_COLS`: `"*"` → `"sm.*"` (query now joins two tables).
* Do NOT touch: `snapshot_meta` schema, `compute/write_snapshots.py`, any migration.

## Commit 2 — frontend: type + StatsPanel display

* Work in: `web/src/api/types.ts`, `web/src/components/panels/StatsPanel.tsx`
* Add `dam_system_lambda: number | null;` to `SnapshotMeta`, matching backend name/position.
* Add a `<Stat>` after `Obj Cost` (`StatsPanel.tsx:96`), formatted `$${fmt(meta.dam_system_lambda, 2)}/MWh` (2 decimals); null falls back to `—` via the existing `{value ?? "—"}`.
* Do NOT touch: correlation sections, scorecard rows, styling.

## Commit 3 — tests

* Work in: `api/tests/test_state.py`
* Since Commit 1 uses a JOIN, `dam_system_lambda` returns as a **column on the meta row** — no separate query. Add it to the `_meta_row` fixture and assert `data['meta']['dam_system_lambda']` in both `/state` and `/state_range` tests. (Do NOT add an extra `cursor.queue(...)` call — the fake cursor stays one queue per real query.)
* `test_openapi.py` needs no change; run it as a regression check.

## Acceptance

* [x] `GET /api/state?t=...` includes `meta.dam_system_lambda` as a float (or `null`). Verified against live DB (e.g. `39.95 $/MWh`).
* [x] `GET /api/state_range` includes `meta.dam_system_lambda` per entry, aligned to each `interval_ts`. `LATERAL ... LIMIT 1` guarantees no row fan-out on DST-doubled hours by construction.
* [x] StatsPanel renders the new `$/MWh` stat, falling back to `—` when null.
* [x] `api/tests/test_state.py` passes with the field asserted in both tests (6 passed incl. `test_openapi.py`).
* [x] No changes to `snapshot_meta` schema, migrations, or `compute/write_snapshots.py`.
