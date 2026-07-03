# CM.1 — correlation-map

Type: feat
Branch: feat/cm.1-correlation-map

## Goal

* Add `compute/mapping/correlation_map.py` that maps each ERCOT SP to its most-correlated model bus over shared hours.
* Persist `mapping_correlation_<run_id>.npz` (`sp_id`, `best_bus`, `best_corr`, `topk_bus`, `topk_corr`) + a summary JSON with % ρ>0.7, % ρ>0.5, median.
* Run against v1-120 pairing the model-side `system_lambda_merit_order` matrix with the ERCOT-side `system_lambda` matrix (same conceptual reference, computed from different sources — model side is null for `system_lambda`, ERCOT side is null for `system_lambda_merit_order`).

## Context

* Two matrices share an hour axis: `model_C` (bus×hour), `ercot_C` (SP×hour), persisted by `compute/matrix.py` into `runs/<id>/matrix/congestion_matrices.npz` as `<ref>_{model,ercot}_C` + `_{bus,sp}_ids` + `_hours`.
* Only `system_lambda_merit_order` is stable (~$29 across regimes); `system_lambda_kkt` is unusable.
* This is the first module of the mapping-first pivot; retires D2 geographic transfer as the translation mechanism.

## Approach

* Create package: `compute/mapping/__init__.py` and file `compute/mapping/correlation_map.py`.
* Loader: read `runs/<run_id>/matrix/congestion_matrices.npz`, select `system_lambda_merit_order_model_C` + `_model_bus_ids` + `_model_hours` for the model side, and `system_lambda_ercot_C` + `_ercot_sp_ids` + `_ercot_hours` for the ERCOT side. Intersect on hours (model and ERCOT hour axes generally differ — matrix.py drops NaN rows independently per side, so v1-120 lands at 107 shared of 120).
* Prefilter: drop rows with `std < var_threshold` (default `1.0` $/MWh, keep as CLI arg). Track dropped ids in the summary.
* Core: Pearson correlation matrix `R[i,j] = corr(model_i, ercot_j)` on shared hours. Use `numpy.corrcoef` on stacked, mean-centered matrices, or `(A_z @ B_z.T)/n` after column-wise z-scoring for memory.
* For each SP j: `best_bus[j] = bus_ids[argmax_i R[i,j]]`, `best_corr[j] = max R[i,j]`, `topk[j] = list of (bus_id, corr)` for k=5 sorted desc; store as JSON string.
* Outputs:
  * `runs/<run_id>/mapping/mapping_correlation_<run_id>.npz` — arrays `sp_id`, `best_bus`, `best_corr`, `topk_bus (n_sp × k)`, `topk_corr (n_sp × k)` sorted descending per SP. (Was parquet in the original plan; switched to npz to stay consistent with the input matrix format and avoid adding `pyarrow`/`fastparquet` to the compute image. Payload is ~40 KB for v1-120, so size is not a concern.)
  * `runs/<run_id>/mapping/mapping_correlation_summary_<run_id>.json` — `run_id, model_ref, ercot_ref, var_threshold, n_sp, n_bus, n_sp_dropped, n_bus_dropped, pct_gt_0_7, pct_gt_0_5, median_corr`.
* Entry point: `python -m compute.mapping.correlation_map --run-id v1-120 [--model-ref system_lambda_merit_order] [--ercot-ref system_lambda] [--var-threshold 1.0] [--topk 5]`. Also supports `--dry-run` (loader shapes only) and `--smoke` (offline planted-signal sanity check for `correlate` + `select_best_and_topk`).
* Do NOT touch: `compute/clustering/*`, `compute/matrix.py`, other reference matrices.

## Sections (commits)

### C1 — scaffold mapping package + loader

* Create `compute/mapping/__init__.py`.
* Add `compute/mapping/correlation_map.py` skeleton with `load_matrices(run_id, ref="system_lambda_merit_order")` returning `(model_C, ercot_C, bus_ids, sp_ids, hours)`.
* Add CLI wiring (argparse) that resolves the run dir via existing runs-layout helpers (see `compute/run_pipeline.py` for the pattern).
* Verify: `python -m compute.mapping.correlation_map --run-id v1-120 --dry-run` prints matrix shapes.

### C2 — implement correlation core + variance prefilter

* Implement `prefilter_low_variance(C, ids, threshold)` returning masked matrix + kept ids + dropped ids.
* Implement `correlate(model_C, ercot_C)` returning `R (n_bus × n_sp)` via z-scored dot product.
* Implement `select_best_and_topk(R, bus_ids, k)` returning best_bus, best_corr, topk records.
* Unit-test-shaped smoke: on random matrices with a planted signal, argmax recovers the planted bus.

### C3 — persist npz + summary + wire CLI

* Write mapping npz + summary JSON to `runs/<run_id>/mapping/`; create dir if missing.
* npz arrays: `sp_id`, `best_bus`, `best_corr`, `topk_bus`, `topk_corr` — the ragged top-k lists are padded to a fixed `k` width so they can serialize as two aligned `(n_sp, k)` matrices (padding: empty string / NaN).
* Summary fields: `run_id, model_ref, ercot_ref, var_threshold, n_sp, n_bus, n_sp_dropped, n_bus_dropped, pct_gt_0_7, pct_gt_0_5, median_corr`.
* Log headline stats to stdout at end of run.
* Verify on v1-120: npz + summary appear; median and >0.5 fraction printed.

## Acceptance

* [x] `compute/mapping/correlation_map.py` runs end-to-end on `--run-id v1-120`.
* [x] `runs/v1-120/mapping/mapping_correlation_v1-120.npz` exists with `sp_id`, `best_bus`, `best_corr`, `topk_bus`, `topk_corr` arrays (top-k sorted descending, padded to fixed k).
* [x] Summary JSON reports `pct_gt_0_7`, `pct_gt_0_5`, `median_corr`, `var_threshold` (plus `model_ref`, `ercot_ref`, `n_sp`, `n_bus`, `n_sp_dropped`, `n_bus_dropped`, `run_id`).
* [x] Prefilter threshold is configurable via `--var-threshold`; dropped counts logged.
* [x] `--smoke` runs an offline planted-signal sanity check with no run data (recovers 15/15 on default seed).
* [x] No writes outside `runs/<run_id>/mapping/`.
* Result on v1-120: median_corr ≈ 0.499, pct>0.7 ≈ 4.7%, pct>0.5 ≈ 49.6% over 935 SPs × 2706 buses on 107 shared hours (soft — flagged for pivot evaluation).
