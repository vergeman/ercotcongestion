# 0054 - matrix-db-driven

Type: refactor
Branch: refactor/0054-matrix-db-driven

## Goal

* Rewrite `compute/matrix.py` to build `congestion_matrices.npz` by streaming from `bus_snapshots` + `snapshot_meta` and the ERCOT tables — no `model_results.json.gz` / `ercot_results.json.gz` inputs.
* Extract `ercot_runner`'s transformation logic into a library module so matrix can call it directly; delete the runner as a pipeline stage.
* Pre-flight: every timestamp requested in `--dates-file` must have `snapshot_meta.status='ok'`. Fail fast with an ingest hint otherwise.

## Context

* [[0053-unified-opf-write-path]] persists every model-side value the pipeline needs directly to Postgres.
* ERCOT data is already fully persisted by the `ercot_ingest` service (`dam_spp`, `system_lambda`, `zone_loads`) — `ercot_runner.py` is a pure DB-read + transform layer with no persistent state of its own.
* Current `matrix.py:57-59` does `records = json.load(f)` on the entire per-record file. At 2751 buses × 13k hours that's projected to hit 5-20 GB resident and OOM on typical dev hardware.
* Hard cut: no legacy JSON fallback. Old runs get re-solved under the new stack.

## Approach

* Work in: `compute/matrix.py`, `compute/congestion/ercot_runner.py`, new `compute/ercot/transforms.py`.
* Entry point / primary change: `compute/matrix.py` `main()` and its record-loading helpers.

**Commit 1 — extract ercot transforms into a library module**

* Create `compute/ercot/transforms.py` (or `compute/congestion/ercot_transforms.py` — pick the location that avoids circular imports with `compute.congestion`).
* Move these pure functions out of `compute/congestion/ercot_runner.py` verbatim: `load_tracked_sps`, `assign_weather_zones`, `fetch_dam_spp_batch`, `fetch_system_lambda_batch`, `fetch_zone_loads_batch`, `build_hub_lmps`, `build_sp_load_weights`, `post_process_one`, `_stats`, `_sanity`.
* Update any lingering import in `ercot_runner.py` to import from the new module (runner still runnable at this commit — deletion is Commit 4).

**Commit 2 — matrix streams model side from DB**

* In `compute/matrix.py`, replace the `json.load(gzip.open(...))` path with:
  * Read timestamps from `--dates-file` (reuse the parser).
  * Pre-flight: single query `SELECT interval_ts, status FROM snapshot_meta WHERE interval_ts = ANY(%s)`. Any ts missing or `status != 'ok'` → exit non-zero with the ingest hint from `run_pipeline._ingest_hint`.
  * Query `bus_snapshots` (interval_ts, bus_id, lmp, modeled_congestion, binding_proximity, dispatch) for the ts list, streamed via a server-side cursor (`cur.itersize = 10_000`).
  * Query `snapshot_meta.hub_lmps` and `snapshot_meta.reference_prices` JSONB for those ts.
  * Pre-allocate `model_C[method] = np.empty((n_bus, n_hours), dtype=float)` per method; fill row-by-row as rows stream in.
* Keep the output shape identical: `congestion_matrices.npz` still has `C_m`, `C_e`, bus/sp indices, hour indices, method names. Downstream (`correlation_map`, `basis_regression`, `cca`, `clustering`, `scorecard`) is unchanged.
* Bounded memory: peak ~1.4 GB for all methods × both sides. Verify with `/usr/bin/time -v` on a 1000-hour slice.

**Commit 3 — matrix streams ERCOT side from DB**

* In the same `main()`, import from the new transforms module and call `fetch_dam_spp_batch`, `fetch_system_lambda_batch`, `fetch_zone_loads_batch` directly against the timestamp list.
* Apply the same transforms (`build_hub_lmps`, `build_sp_load_weights`, `post_process_one`) inline to build the ERCOT `C_e` matrices.
* Pre-flight: if any requested ts has no `dam_spp` rows, exit with a clear ercot-ingest hint (mirror the model-side pattern).
* Save `congestion_matrices.npz` in the same location as today (`compute/runs/<run_id>/matrix/`).

**Commit 4 — delete ercot_runner as a pipeline stage**

* Delete `compute/congestion/ercot_runner.py`.
* `git grep ercot_runner` — remove call sites. `run_pipeline.py` stage list cleanup is fully covered in [[0055-run-pipeline-surgery]]; here just delete the module.
* Update `compute/README.md` §"Debugging individual stages" — remove the ERCOT congestion entry; add matrix's new `--dates-file` invocation.

* Do NOT touch: `compute/mapping/*`, `compute/clustering/*`, `compute/scorecard*`. Their npz consumption contract is stable.

## Acceptance

* [x] `python -m compute.matrix --run-id <id> --dates-file <path>` produces `congestion_matrices.npz` with the same array names/shapes as the pre-refactor output on the same dates.
* [ ] Peak resident memory for a 13k-hour run stays under 4 GB (measured via `/usr/bin/time -v`).
* [x] Missing `snapshot_meta.status='ok'` on any requested ts → non-zero exit with the ingest hint printed to stderr, no partial `.npz` written.
* [x] `git grep -E 'model_results\.json|ercot_results\.json'` returns no hits in `compute/` outside of docs describing historical behavior.
* [x] `compute/mapping/correlation_map.py --run-id <id>` runs unchanged against the new npz.
