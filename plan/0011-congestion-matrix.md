# 0011 - congestion-matrix (model-side)

Type: feat
Branch: feat/0011-congestion-matrix
Status: done

## Goal (revised)

Build congestion matrix, infrastructure only: extend `congestion_snapshot.py`
with another reference method generator weighted; a per-record sanity block, and
a `--dates-file` CLI flag. Defer all structural diagnostics (PCA, pairwise-corr,
cluster stability) and reference-method selection when comparing model vs ERCOT.

## Added

* `congestion.py`:
  * New method `gen_weighted = lmps − Σ(lmps × dispatch) / Σ(dispatch)`;
    `compute_congestion` gained a `dispatch` parameter.
  * `build_congestion_matrix(records, ref_method)` but used later
  * `pca_variance_explained`, `pairwise_corr_distribution`,
    `split_half_cluster_stability` present as `NotImplementedError` stubs —
    signatures preserved for later phase.
* `congestion_snapshot.py`:
  * `build_dispatch_per_bus` helper; dispatch passed into `compute_congestion`.
  * Old per-method `stats` block dropped; replaced with a `sanity` block
    (`simple_mean_centered`, `abs_max`, `n_extreme`).
  * `system_lambda_proxy` field renamed to `system_lambda`. Value unchanged
    (`lmps.median()`). Energy-balance dual was rejected because the load-
    weighted nodal-balance dual is mathematically identical to the existing
    `load_weighted` reference method.
  * `--dates-file PATH` CLI flag (accepts both flat-list and
    dict-of-regimes schemas).
  * Final summary line: `n_records / n_ok / n_missing / n_extreme_buses`.

## Deferred

* PCA / pairwise-corr / cluster-stability — meaningful only model vs ERCOT.
* Reference-method selection.
* Persistence of matrices (parquet).
* Idempotency / OPF-solve caching.
* Energy-balance dual as system_lambda (open question; revisit if a
  non-duplicate formulation is wanted).

## Verification

Ran end-to-end on `compute/profiling/reference_dates.json` via
`congestion_snapshot.py --run-id matrix-smoke`: 20/20 records ok, six methods in
each `congestion` block, summary line, and sanity tests present.
