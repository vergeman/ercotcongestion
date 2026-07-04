# 0053 - unified-opf-write-path

Type: refactor
Branch: refactor/0053-unified-opf-write-path

## Goal

* Make `write_snapshots.py` the single OPF entry point. Populate every column added in [[0052-opf-persistence-schema]] at solve time.
* Delete `compute/congestion/snapshot_runner.py` — no second OPF codepath.
* Keep the per-hour UPSERT + `--skip-existing` semantics that already make `write_snapshots.py` crash-safe and parallelizable across containers.

## Context

* `write_snapshots.py` already runs DC-OPF per hour and commits `bus_snapshots` + `snapshot_meta` transactionally. It just doesn't persist the scalars/dispatch that the analytical pipeline needs.
* `compute/congestion/snapshot_runner.py` runs the same OPF but writes a single `model_results.json.gz` at end-of-run — all-or-nothing, no crash resume, no parallelism. It becomes redundant once `write_snapshots.py` persists everything.
* Downstream ([[0054-matrix-db-driven]]) will read all analytical inputs directly from the DB. There's no `model_results.json.gz` consumer once that branch lands.
* `--force-recompute` on `write_snapshots.py` must be able to fill new columns for existing rows (no schema-version gating).

## Approach

* Work in: `compute/write_snapshots.py`, `compute/congestion/`.
* Entry point / primary change: `write_snapshot(conn, ts, result, op, network)` in `compute/write_snapshots.py`.

**Commit 1 — compute + persist the new scalars in `snapshot_meta`**

* In `write_snapshot`, after `compute_snapshot_batch` returns:
  * Compute `system_lambda_kkt` via `lambda_kkt_clean_median(n, ts)` (copy the call pattern from `compute/congestion/snapshot_runner.py:200`).
  * Compute `system_lambda_merit_order` via `lambda_merit_order(n, ts)` (pattern from `snapshot_runner.py:210`).
  * Extract `load_shed_mw = result['meta'].get('load_shed_total_mw', 0.0)`.
  * Build `hub_lmps` via `build_hub_lmps(lmps, n, hub_centroids)` — load `hub_centroids` once at module init, not per call.
  * Build `reference_prices` by calling `compute_congestion(...)` and taking its `refs` return; this reuses the existing method set.
* Extend `UPSERT_META_SQL` and its parameter tuple to include the four new fields (`hub_lmps`, `reference_prices` as `%s::jsonb`).
* Wrap the three new scalar computations in the same try/except pattern as `snapshot_runner.py` — a failure in one leaves the column NULL, doesn't abort the write.

**Commit 2 — persist per-bus dispatch in `bus_snapshots`**

* In `write_snapshot`, derive per-bus dispatch: `dispatch_per_bus = build_dispatch_per_bus(result['dispatch'], n)` (function lives in `snapshot_runner.py:122` — move it to `compute/congestion/metrics.py` so both call sites can import).
* Extend `UPSERT_BUS_SNAPSHOT_SQL` to include `dispatch`, and append `_f(dispatch_per_bus, bus_id)` to each row tuple.
* NULL is the correct value for buses with no generators — don't fabricate 0.

**Commit 3 — delete snapshot_runner and the file-based congestion path**

* Delete `compute/congestion/snapshot_runner.py` entirely.
* Any imports of it (grep for `snapshot_runner`) — remove call sites. Notably `compute/run_pipeline.py:_stage_cmd` — that gets cleaned up fully in [[0055-run-pipeline-surgery]], but on this branch just remove the stage entry so nothing references the deleted module.
* Move `build_dispatch_per_bus`, `build_load_per_bus`, and `build_hub_lmps` from the deleted file into `compute/congestion/metrics.py` (or similar) if they aren't already there. Keep them as pure functions; both `write_snapshots.py` and future callers should import from one place.
* Delete `sample-recompute-gate` and any docs referring to `model_results.json.gz` as an artifact. `docs/sample-recompute-gate-results.md` — decide whether to preserve as historical or delete.

**Commit 4 — README refresh**

* Update `compute/README.md` §1 to state clearly: `write_snapshots.py` is the single OPF path; it persists everything the analytical pipeline needs.
* Update §4 to remove references to per-record JSON outputs from congestion. `run_pipeline.py` docs stay as-is on this branch (updated in [[0055-run-pipeline-surgery]]).
* Add a "parallelize" subsection under §1: fan out disjoint `--start`/`--end` ranges to N containers; `--skip-existing` handles boundary overlap. Suggested worker count: 4-6 per compute box (~1-2 GB per PyPSA solver + adapter).

* Do NOT touch: `compute/matrix.py`, `compute/run_pipeline.py` stage list beyond the minimal removal, `compute/congestion/ercot_runner.py`.

## Acceptance

Implementation:

* [x] `write_snapshot()` computes and persists `system_lambda_kkt`, `system_lambda_merit_order`, `load_shed_mw`, `hub_lmps`, `reference_prices` — each in its own try/except so a per-scalar failure leaves the column NULL rather than aborting the write.
* [x] `write_snapshot()` computes `dispatch_per_bus` via `build_dispatch_per_bus` and writes it into `bus_snapshots.dispatch`; the helper no longer `fillna(0.0)`, so buses with no generators land as NULL.
* [x] `UPSERT_META_SQL` / `UPSERT_BUS_SNAPSHOT_SQL` extended with the new columns + matching `ON CONFLICT … DO UPDATE`; `write_failure` tuple padded to match arity.
* [x] `_HUB_CENTROIDS` loaded once at module init in `write_snapshots.py`.
* [x] `compute/congestion/snapshot_runner.py` deleted; `build_hub_lmps`, `build_load_per_bus`, `build_dispatch_per_bus`, and `HUB_K_NEAREST` moved to `compute/congestion/metrics.py` as the single source of truth.
* [x] `compute.run_pipeline.STAGES` no longer contains `"congestion"`; matching branches removed from `_stage_outputs` / `_stage_cmd`. Downstream file-based consumption (`matrix.py`) intentionally left untouched — resolved in [[0054-matrix-db-driven]].
* [x] `compute/README.md` §1 restated as single OPF path + new "Parallelize across containers" subsection; §4 stage flow updated to `ERCOT → matrix → …`; `--records-output` removed from the flags list.

Runtime verification (still to run against a live DB):

* [ ] `write_snapshots.py --start T --end T+1h` produces a row in `snapshot_meta` where `system_lambda_kkt`, `system_lambda_merit_order`, `load_shed_mw`, `hub_lmps`, `reference_prices` are all non-NULL for a normal (`status='ok'`) snapshot.
* [ ] `bus_snapshots.dispatch` is non-NULL for buses with generators, NULL for buses without.
* [ ] `--force-recompute` over an existing hour populates the new columns without changing `lmp` / `modeled_congestion` / `binding_proximity` beyond floating-point noise.
* [ ] Two `write_snapshots.py` containers running on disjoint date ranges complete without deadlock or duplicate-key errors.

Static grep:

* [x] `git grep snapshot_runner` returns no hits in `compute/write_snapshots.py`, `compute/run_pipeline.py`, or under `compute/congestion/`. Residual matches remain in `compute/matrix.py`'s docstring, README §2 experiment invocations, and `compute/experiments/{shed_canary,hub_k_sweep}/*` — all on the plan's explicit "do NOT touch" list and cleared in [[0054-matrix-db-driven]] / [[0055-run-pipeline-surgery]].
