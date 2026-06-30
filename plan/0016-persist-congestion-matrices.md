# 0016 - persist-congestion-matrices

Type: feat
Branch: feat/0016-persist-congestion-matrices

## Goal

* `congestion_matrix.py` writes a sidecar `congestion_matrices_<run_id>.npz` containing the raw bus×hour matrices already built in-memory for each ref method.
* No change to the existing `congestion_matrix_<run_id>.json`; the npz is additive.
* Sidecar round-trips: a consumer can recover `C_model` and `C_ercot` per ref method, plus aligned bus/SP/hour indices.

## Context

* `congestion_matrix.py::_build_matrix` already constructs the per-(ref_method, source) matrix that diagnostics consume; it is thrown away after `pca`/`pairwise_corr`/`cluster_stability` summarize it.
* Phase 3 (0017+) clusters those same matrices. Re-deriving them downstream would require parsing the JSON record list a second time and reapplying the NaN-drop convention; persisting once at source is cheaper and keeps a single definition of "the matrix Phase 2 analyzed."
* Drop-NaN happens inside `pca_variance_explained` today. To make the npz match what diagnostics saw, drop NaN once at the top of each ref-method block in `main()` and feed the cleaned matrix to all downstream calls AND to the npz writer.

## Approach

* Work in: `compute/experiments/congestion_calculation/congestion_matrix.py`.
* Entry point: `main()`, inside the per-ref-method loop.
* Add a helper `_drop_nan_buses(C: pd.DataFrame) -> tuple[pd.DataFrame, int]` near `_build_matrix`. Returns cleaned matrix + count dropped. Use it for both sides (model, ercot) so the npz, PCA, pairwise-corr, and cluster-stability all see the same matrix.
* Add `_write_matrices_npz(path, matrices_by_ref, indices) -> None`:
  * `matrices_by_ref` is a dict `{ref_method: {"model_C": ndarray, "ercot_C": ndarray}}`. Either side may be a zero-shape array if the ref method is one-sided (e.g. `system_lambda_kkt` model-only, `system_lambda` ERCOT-only) — preserve the existing asymmetry rather than padding.
  * `indices` carries `{ref_method}_model_bus_ids`, `{ref_method}_ercot_sp_ids`, `{ref_method}_model_hours`, `{ref_method}_ercot_hours` as object arrays. Hours are the `(regime|ts)` column keys produced by `_col_key`; they may differ across ref methods if NaN-drop kicks out different rows (it shouldn't in practice, but don't assume).
  * Use `np.savez_compressed`. ndarrays only; no pickled objects. Bus IDs as fixed-width string arrays.
* In `main()`:
  * Accumulate `matrices_by_ref` and `indices` while looping.
  * After the loop, call `_write_matrices_npz(json_path.with_name(f"congestion_matrices_{run_id}.npz"), ...)`.
  * Log `wrote {path} (n_refs={...}, total_bytes={...})`.
* Do NOT touch: `congestion.py`, `congestion_snapshot.py`, `ercot_congestion_snapshot.py`, the JSON output schema. Do NOT change which buses get dropped — match current `pca_variance_explained` behavior exactly (drop any row with at least one NaN).

## Status

Implemented in `congestion_matrix.py`. Verified on `congestion_results_final-merit.json` (run_id `test-persist`): npz has 48 keys (8 refs × 6), shapes align with index arrays, `C.shape[0]` matches `pca.n_buses` on all non-null PCA blocks (model 2737, ercot 940), one-sided methods land as `(0,0)`. JSON byte-identity vs baseline not yet diffed.

## Acceptance

* [ ] `python compute/experiments/congestion_calculation/congestion_matrix.py --model-results ...congestion_results_final-merit.json` produces both the existing JSON and a new `congestion_matrices_final-merit.npz` in the same directory.
* [ ] `np.load(path)` exposes keys `lmp_median_model_C`, `lmp_median_ercot_C`, `lmp_median_model_bus_ids`, `lmp_median_ercot_sp_ids`, `lmp_median_model_hours`, `lmp_median_ercot_hours` (and the equivalents for the other 7 methods).
* [ ] `lmp_median_model_C.shape == (len(lmp_median_model_bus_ids), len(lmp_median_model_hours))`.
* [ ] For methods that produced a non-null `pca` block in the existing JSON, `C.shape[0]` in the npz equals `pca.n_buses` (i.e. NaN-drop is consistent).
* [ ] One-sided methods (`system_lambda` ERCOT-only, `system_lambda_kkt` and `system_lambda_merit_order` model-only): the absent side is present as a zero-shape ndarray with its corresponding index array empty.
* [ ] Existing JSON is byte-identical to a pre-change run on `congestion_results_final-merit.json` (verify with `diff`).
