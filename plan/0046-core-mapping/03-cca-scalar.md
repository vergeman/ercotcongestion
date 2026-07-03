# CM.3 — cca-scalar

Type: feat
Branch: feat/cm.3-cca-scalar

## Goal

* Add `compute/mapping/cca.py` computing CCA between `model_C.T` and `ercot_C.T` (hours as samples); report top canonical correlations as the system-level "shared structure" scalar.
* Cross-check: correlate model vs ERCOT top principal temporal components; report pairwise correlations.
* Persist `mapping_cca_<run_id>.json` (top-N canonical correlations, PC cross-corr).

## Context

* Complements [[01-correlation-map]] (SP-level) and [[02-basis-regression]] (SP-level R²) with a single system-level scalar.
* May extend or share code with Tier-5 eigenstructure validation (`compute/congestion/*` — check for existing PCA helpers before adding).
* n_features (buses/SPs) likely > n_samples (hours) on shorter windows — use ridge-regularized CCA (`sklearn.cross_decomposition.CCA` or explicit SVD-of-whitened form).

## Approach

* Work in: `compute/mapping/cca.py`. Reuse loader from CM.1/CM.2.
* Fit CCA with `n_components = min(n_top, rank(model_C), rank(ercot_C))`, default `n_top=5`.
* Compute canonical correlations = correlation of paired canonical variates on training data. Report top 5.
* PC cross-check: SVD both `model_C` and `ercot_C` (hours as samples), take top-k=5 right singular vectors from each, compute pairwise Pearson correlation matrix (5×5); report diagonal and best-match permutation correlations.
* Output JSON: `{canonical_correlations: [...], pc_cross_corr: [[...]], pc_best_match_diag: [...], n_components, ref, run_id}`.
* Entry point: `python -m compute.mapping.cca --run-id v1-120 [--n-components 5]`.
* Do NOT touch: clustering, matrix builder.

## Sections (commits)

### C1 — CCA fit + top canonical correlations

* Implement `fit_cca(model_C, ercot_C, n_components) -> canonical_correlations`.
* Use sklearn CCA; fall back to explicit form if numerical issues.
* Smoke: two matrices with a shared latent get near-1 top canonical corr.

### C2 — PC cross-correlation cross-check + persist

* Implement `pc_cross_corr(model_C, ercot_C, k=5) -> (matrix, diag, best_match_perm)`.
* Write `runs/<run_id>/mapping/mapping_cca_<run_id>.json`.
* CLI logs top-1 canonical corr and PC-1 cross corr.
* Verify on v1-120: JSON exists; top canonical corr reported.

## Acceptance

* [ ] `compute/mapping/cca.py` runs on `--run-id v1-120`.
* [ ] Output JSON has `canonical_correlations` (length ≤ n_components) and `pc_cross_corr` matrix.
* [ ] Handles rank-deficient inputs without crashing.
* [ ] Headline top canonical correlation logged.
