# 0052 - opf-persistence-schema

Type: feat
Branch: feat/0052-opf-persistence-schema

## Goal

* Extend `snapshot_meta` and `bus_snapshots` (or add a side table) so a single OPF solve captures every value the analytical pipeline needs downstream.
* Preserve UPSERT idempotency so [[0053-unified-opf-write-path]] can populate the new columns via `--force-recompute` on existing rows.
* Ship as a single DB migration so a fresh DB and the current dev DB reach the same schema.

## Context

* Today `bus_snapshots` persists per-bus `lmp`, `modeled_congestion`, `binding_proximity`, `basis`. `snapshot_meta` persists per-ts aggregates + `dispatch_by_carrier` JSONB (carrier-aggregated only).
* Downstream ([[0054-matrix-db-driven]]) needs per-ts `system_lambda_kkt`, `system_lambda_merit_order`, `load_shed_mw`, per-bus `dispatch`, and `hub_lmps` — none of these are recoverable from what's currently stored.
* Hard cut: no backwards compatibility with `model_results.json.gz` — historical runs (`v1-120`, `v1-full-dev`) will be re-solved fresh under the new schema.
* Migration numbering follows `db/migrations/NN_*.sql`; last is `18_congestion_metrics.sql`. Use `19_opf_persistence.sql`.

## Approach

* Work in: `db/migrations/`, plus a compose/init check to confirm the migration runs on container start.
* Entry point / primary change: new file `db/migrations/19_opf_persistence.sql`.

**Commit 1 — schema migration**

* Add columns to `snapshot_meta`:
  * `system_lambda_kkt double precision`
  * `system_lambda_merit_order double precision`
  * `load_shed_mw double precision`
  * `hub_lmps jsonb` — `{"HB_NORTH": 42.13, "HB_HOUSTON": 45.67, ...}` (all 4 hubs; keep k-nearest averaging in the write path, not on read).
  * `reference_prices jsonb` — `{"lmp_median": 41.9, "load_weighted": 43.2, ...}` cached scalar refs per method so matrix.py doesn't recompute.
* Add column to `bus_snapshots`:
  * `dispatch double precision` — per-bus generator dispatch MW (sum over all gens at the bus). NULL for buses with no generators.
* Use `ADD COLUMN IF NOT EXISTS` (idempotent). No new indexes — these columns aren't filter predicates.
* Follow the additive pattern from `18_congestion_metrics.sql` — no drops, no renames.

**Commit 2 — apply and verify**

* Run migration against the local dev DB via the existing bootstrap path (whatever `docker compose up` triggers on schema init — verify the migration runs).
* Add a short section to `docs/db.md` (or wherever schema is documented; create if missing) listing the new fields with one-line semantics each.
* Do NOT touch: writer code (`write_snapshots.py`, `snapshot_runner.py`). Those changes are [[0053-unified-opf-write-path]].

## Acceptance

* [x] `19_opf_persistence.sql` exists and applies cleanly to a fresh DB.
* [x] `19_opf_persistence.sql` applies idempotently to an already-migrated DB (re-running is a no-op).
* [x] `\d snapshot_meta` shows the four new columns with correct types.
* [x] `\d bus_snapshots` shows the `dispatch` column.
* [x] No writer code has been changed on this branch — the columns exist and are NULL on all existing rows.
