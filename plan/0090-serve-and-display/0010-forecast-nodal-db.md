# 0010 - forecast-nodal-db

Type: feat
Branch: feat/0010-forecast-nodal-db

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add the `forecast_nodal` panel table and this feature's own `forecast_current` pointer (migration `30_forecast_nodal.sql`).
* Provide `nodal_to_db(npz, conn)` that `COPY`s a `load_nodal` panel into `forecast_nodal`, and a `--to-db` flag on `propagate` that writes the panel + upserts the pointer.
* Keep the write idempotent per `(run_id, delivery_date)` and flip the pointer last, so a reader never sees a half-written day.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase2a-nodal-panel.md` §0 (precompute the panel — no per-request parameter), §5(b) (Postgres primary for serving), §6 (schema), §11 (wire `nodal_to_db` now so backtest + production land in one table). Depends on **0009** (`load_nodal`); do it first.
* Serving already reads from Postgres; the DB is the substrate the API resolves per request. This feature **owns its own table + pointer** — no `compute/promote.py`, no legacy symlink tree, no `implied_binding_proximity_current` (spec §5b, §6).
* Backtest bulk (npz→DB) and production single-day writes (0011 / phase2b) must converge on the same `forecast_nodal` so the Phase-4 slider serves from the same endpoint as tomorrow's forecast.
* `sf_r2` (per-SP fit confidence) rides the existing IBP diagnostics, not this table (spec §6).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `db/migrations/30_forecast_nodal.sql` (new), `compute/mu/propagate.py` (`nodal_to_db`, `--to-db`), plus a small pointer-upsert helper.
* **Migration `30_forecast_nodal.sql`** — verbatim from spec §6:
  * `forecast_nodal (run_id text, delivery_date date, ts timestamptz, settlement_point text, p10 real, p50 real, p90 real, point real, PRIMARY KEY (run_id, ts, settlement_point))`.
  * `forecast_current (layer text PRIMARY KEY, run_id text NOT NULL, promoted_at timestamptz NOT NULL DEFAULT now())` — this feature's pointer; `layer='ercot'`.
  * Do **not** create `forecast_sf_artifact` here — that ships in 0011.
* **`nodal_to_db(npz_path, conn, *, run_id, delivery_date=None)`** — `load_nodal` → `psycopg` `COPY` into `forecast_nodal`. Idempotent: delete-then-copy (or `COPY` to temp + upsert) scoped to the `(run_id, delivery_date)` written, so a re-run replaces cleanly (spec §5b, and phase2b §6).
* **`upsert_pointer(conn, layer, run_id)`** — `INSERT ... ON CONFLICT (layer) DO UPDATE`. Called **after** rows land; never before.
* **`--to-db`** on the CLI (spec §8): after (or alongside) `--nodal-out`, `COPY` the panel into `forecast_nodal` and upsert the pointer. `run_id` names the model version (e.g. `mu-all-v1`, phase2b §4), passed as a CLI arg, not derived from the day.
* Do NOT touch: `compute/promote.py`, the legacy pointer/symlink path, `api/` endpoints (Phase 2 serving is separate), driver rows / SF+μ artifact (0011).

## Commits

<!-- Grouped so the migration applies and the loader round-trips at branch end. -->

* **Commit A — `feat(db): forecast_nodal + forecast_current (migration 30)`**
  * `db/migrations/30_forecast_nodal.sql` — the two tables (spec §6).
* **Commit B — `feat(propagate): nodal_to_db COPY loader + pointer upsert`**
  * `propagate.py` — `nodal_to_db`, `upsert_pointer`; idempotent delete-then-copy per `(run_id, delivery_date)`, pointer flipped last.
* **Commit C — `feat(propagate): --to-db writes panel + flips pointer`**
  * `propagate.py` — CLI `--to-db` (+ `run_id` arg); wires the loader + pointer into the run. No-flag path unchanged.
* **Commit D — `test(propagate): forecast_nodal load idempotency + pointer atomicity`**
  * `compute/mu/tests/` — `nodal_to_db` twice yields identical rows and one pointer row; pointer upserts after rows exist; PK collisions replace, not duplicate.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] Migration 30 applies; `forecast_nodal` + `forecast_current` exist with the spec §6 columns/PKs.
* [x] `nodal_to_db(out.npz, conn, run_id=...)` `COPY`s the backtest panel; row count matches `load_nodal`; `point` and `p50` both populated and distinct.
* [x] Re-running `nodal_to_db` for the same `(run_id, delivery_date)` replaces rows idempotently; `forecast_current[ercot]` holds exactly one row for the run.
* [x] Pointer is upserted only after rows land (no half-written day visible); no legacy `promote`/symlink/`ibp` path is touched.
