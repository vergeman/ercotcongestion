# CM.2 — basis-regression

Type: feat
Branch: feat/cm.2-basis-regression

## Goal

* Add `compute/mapping/basis_regression.py`: PCA model matrix over hours → top-k temporal components `f_k(t)`; per-SP OLS `ercot_j(t) ≈ Σ_k β_jk f_k(t) + ε` with R².
* Persist `mapping_basis_<run_id>.npz` (SP, r2, betas) + summary (k chosen, cumulative variance explained, R² distribution).
* R² is the primary translation metric — "how much of SP j the model explains."

## Context

* Uses the same fixed reference matrix (`system_lambda_merit_order`) and the same `runs/<run_id>/matrix/congestion_matrices.npz` loader as CM.1 [[01-correlation-map]].
* Congestion matrices are low-rank in practice; expect k ∈ 3..8 for ~90% cumulative variance.
* Existing SVD patterns to mirror: `compute/clustering/algorithm.py::pca_kmeans` and `compute/congestion/*::pca_variance_explained`. Orientation here: center **across buses** (rows), scores are `U*S` but keep temporal components `f_k(t)` (right singular vectors interpreted as time signals).

## Approach

* Work in: `compute/mapping/basis_regression.py`.
* Reuse `load_matrices` from `compute/mapping/correlation_map.py` (extract to `compute/mapping/_io.py` if cleaner).
* PCA/SVD on `model_C` with `hours` as sample axis: shape it so components are functions of time. Choose k = smallest such that cumulative explained variance ≥ `--var-target` (default 0.90); allow `--k` override.
* Per-SP OLS via closed form: `β_j = (F^T F)^{-1} F^T y_j`, `y_j = ercot_C[j, :]`, `F = [f_1, ..., f_k]` (hours × k). Compute R² = `1 - SS_res/SS_tot`.
* Output npz: `sp_id, r2, betas` (betas is an `(n_sp, k)` float matrix).
* Summary JSON: `k, cumulative_var, r2_median, r2_p25, r2_p75, pct_r2_gt_0_5, pct_r2_gt_0_7, ref`.
* Entry point: `python -m compute.mapping.basis_regression --run-id v1-120 [--var-target 0.90] [--k K]`.
* Do NOT touch: clustering modules, matrix builder, other reference matrices.

## Sections (commits)

### C1 — PCA components from model matrix

* Implement `fit_components(model_C, var_target, k_override) -> (F, singular_values, cumvar, k)`.
* Center across buses (per-hour mean removed only if that matches Tier-5 convention — otherwise center per-bus; document choice in a one-line comment).
* Smoke test: on a rank-3 synthetic matrix, `k` converges to 3 at var_target=0.99.

### C2 — per-SP OLS + R²

* Implement `regress_all_sps(F, ercot_C) -> (betas [n_sp × k], r2 [n_sp])` using `np.linalg.lstsq` or explicit normal equations (F is small).
* Handle zero-variance SP rows: R² = NaN, betas = zeros; count in summary.
* Verify: perfectly-linear synthetic SP recovers R² ≈ 1.

### C3 — persist npz + summary + CLI

* Write `runs/<run_id>/mapping/mapping_basis_<run_id>.npz` and `..._summary_<run_id>.json`.
* CLI logs headline: `k=<k>, cumvar=<...>, median R²=<...>, %R²>0.5=<...>`.
* Verify on v1-120: outputs written; k reported in 3..8 range.

## Acceptance

* [x] `compute/mapping/basis_regression.py` runs on `--run-id v1-120`.
* [x] `runs/v1-120/mapping/mapping_basis_v1-120.npz` has `sp_id, r2, betas` arrays; betas has shape `(n_sp, k)`. Verified: `(940,)`, `(940,)`, `(940, 6)`.
* [x] Summary JSON records `k`, `cumulative_var`, R² percentiles. On v1-120 default (`--var-target 0.90`): `k=6`, `cumulative_var=0.902`, `r2_median=0.301`, `r2_p25=0.213`, `r2_p75=0.372`, `pct_r2_gt_0_5=5.1%`, `pct_r2_gt_0_7=0.5%`.
* [x] Zero-variance SPs surfaced (not crashed on): `r2 = NaN`, `betas = 0`, counted in `n_sp_zero_var` (0 in v1-120; mechanism covered by `_smoke_regress_all_sps`).
* [x] `--var-target` and `--k` CLI overrides work: `--k 3` → k=3, cumvar 0.765, median R² 0.185; `--var-target 0.99` → k=19, cumvar 0.991, median R² 0.589.

## Notes

* Sensitivity: bumping `--var-target` from 0.90 (k=6) to 0.99 (k=19) lifts median R² from 0.301 to 0.589 and %R²>0.5 from 5% to 57%. Default 0.90 may be leaving explanatory power on the table — worth revisiting when downstream consumers exist.
* OLS augments `F` with a ones column internally so R² is measured against the standard SS_tot = Σ(y − mean(y))². Only the k component betas are stored; the intercept is discarded (it's an artifact of centering).
* Added `pyarrow` was NOT required — this branch uses npz per user direction; no new dependencies.
