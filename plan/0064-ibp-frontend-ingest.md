# 0064 - ibp-frontend-ingest

Type: feat
Branch: feat/0064-ibp-frontend-ingest

## Goal

* Move a promoted `bp_ercot` run from on-disk npz into Postgres so the API can serve it.
* Add an ingest stage that populates the DB table from `runs/<run_id>/ibp/bp_ercot.npz`.
* Expose a way for the frontend to pick which run is "current" without a redeploy.

## Context

* `compute.implied_binding_proximity` currently writes only npz — fine for compute-side sweeps, not for API queries.
* Hyperparameter-sensitive output: different `(window, refit, λ)` combos produce meaningfully different `bp_ercot`. Whatever we persist needs a parameter-set identifier so we can swap runs.
* Related: plan 0057 (binding proximity fix) and existing DAM SPP / shadow-price ingest patterns (plan 0061).

## Discussion — decide before implementing

The shape of this stage depends on a few choices. Confirm with the user before writing code.

**D1 — DB schema shape.** Options:
* **(a) Long table**: `implied_binding_proximity(ts TIMESTAMPTZ, settlement_point TEXT, bp REAL, run_id TEXT)`, PK `(run_id, ts, settlement_point)`, index on `(run_id, ts)`. ~4.4M rows per promoted run. Cleanest joins to `settlement_points`. **Recommended.**
* **(b) JSONB per hour**: `implied_binding_proximity(ts, run_id, bp JSONB)` with `bp = {sp: value, ...}`. Denser (~4k rows/run), one row per API request. Loses SP-level indexability.
* **(c) Wide array**: `implied_binding_proximity(ts, run_id, bp REAL[])` + a separate `sp_order` metadata row. Compact, awkward.

**D2 — Promotion mechanism.** How does the API know which run to serve?
* **(a) `current_run` pointer table**: `implied_binding_proximity_current(layer TEXT PK, run_id TEXT)`. One row: `('ercot', 'ibp_sweep_w60_r7_l1e-2')`. Flip in one UPDATE. **Recommended.**
* **(b) Convention**: hardcode a run_id in backend config. Simpler, requires a redeploy to swap.
* **(c) Latest wins**: no promotion, always serve `MAX(created_at)`. Rejects sweep runs polluting the "live" view unless we tag them.

**D3 — Sweep vs promoted runs in DB.** Do sweep runs land in the DB too?
* **(a) Only promoted runs get ingested.** Sweeps stay on disk. Fastest, keeps the table small. **Recommended.**
* **(b) All runs land, current pointer selects.** Simple but 4.4M × N rows.

**D4 — Ingest trigger.** How does ingest happen?
* **(a) Separate CLI**: `python -m compute.implied_binding_proximity.ingest --run-id <id>`. Explicit, run when you promote. **Recommended.**
* **(b) Pipeline stage after ibp**: automatic. Fine only if D3=(b).
* **(c) `runner.py` writes both npz and DB.** Couples fit to persistence; awkward for sweeps.

Default assumption below: **D1(a) + D2(a) + D3(a) + D4(a).** Change the approach if the user redirects.

## Approach

Assuming the defaults above.

### Migration

* Work in: `db/migrations/` (or wherever plan 0061 landed its migration — mirror that).
* Create tables:
  * `implied_binding_proximity(ts TIMESTAMPTZ NOT NULL, settlement_point TEXT NOT NULL, bp REAL NOT NULL, run_id TEXT NOT NULL, PRIMARY KEY (run_id, ts, settlement_point))` with index on `(run_id, ts)`.
  * `implied_binding_proximity_current(layer TEXT PRIMARY KEY, run_id TEXT NOT NULL, promoted_at TIMESTAMPTZ NOT NULL DEFAULT now())`.
* Do NOT drop or rename existing tables. Additive migration only.

### Ingest CLI

* Work in: `compute/implied_binding_proximity/ingest.py` (new file).
* Entry point: `main()` with `--run-id`, `--layer` (default `ercot`), `--promote` (bool flag).
* Behavior:
  * Load `runs/<run_id>/ibp/bp_ercot.npz`.
  * Verify `params.ref_method == "system_lambda"` (bail otherwise).
  * `DELETE FROM implied_binding_proximity WHERE run_id = %s` (idempotent re-ingest).
  * Bulk `COPY FROM STDIN` with the hour×SP grid unpivoted to long rows. Batch to keep memory bounded — the panel is 4.4M rows.
  * If `--promote`: `INSERT INTO implied_binding_proximity_current(layer, run_id) VALUES (%s, %s) ON CONFLICT (layer) DO UPDATE SET run_id = EXCLUDED.run_id, promoted_at = now()`.
* Do NOT modify `runner.py`. Ingest is a separate concern.

### API surface (out of scope for this plan — flag for follow-up)

* The backend endpoint that reads this table is a follow-up. Note whichever backend module owns the map-layer feed and file a follow-up plan referencing this one. Suggested query shape: `SELECT settlement_point, bp FROM implied_binding_proximity WHERE ts = %s AND run_id = (SELECT run_id FROM implied_binding_proximity_current WHERE layer = 'ercot')`.
* Filed as [plan 0065 - ibp-api-endpoint](0065-ibp-api-endpoint.md).

## Acceptance

* [x] Migration applies cleanly; both tables exist with correct PK/indexes.
* [x] `python -m compute.implied_binding_proximity.ingest --run-id <id>` populates `implied_binding_proximity` with row count = `hours × settlement_points` from the npz.
* [x] Re-running ingest for the same `run_id` is idempotent (no dup-key error, row count unchanged).
* [x] `--promote` flips the pointer; sets the expected SP list for a known hour.
* [x] Follow-up plan for the API endpoint is filed and linked from this doc.
