# CM.6 — ranking-demotion

Type: refactor
Branch: refactor/cm.6-ranking-demotion

## Goal

* Drop `sil_ercot`/`sc_ercot` from `select_zones.py`; composite score → model-side legibility only (`sil_model`, `sc_model`).
* Stop sweeping the reference-price axis; run clustering on the single fixed `system_lambda_merit_order` matrix.
* Cluster on Stage-B β-loadings (from CM.2 basis regression), not raw vectors. Keep `hierarchical_on_β` (primary) + `hybrid_geo` (optional fallback). Retire `kmeans_vec` and `pca_kmeans`.

## Context

* Ranking is now a *presentation-tier selector*, not a validity score — CM.1–CM.3 own validity ([[01-correlation-map]], [[02-basis-regression]], [[03-cca-scalar]]).
* Model-side congestion is translation-invariant across the reference-price choice on the model side; sweeping ref is redundant work.
* β-loadings from CM.2 are a lower-dimensional, denoised representation of each bus's temporal behavior — clustering on β aligns algorithms with the new translation metric.
* Depends on [[04-retire-geo-transfer]] (sil_ercot/sc_ercot already dropped from cell results) and [[05-polygons-display-only]] (polygons not on the ranking path).

## Approach

* Work in: `compute/clustering/select_zones.py`, `compute/clustering/algorithm.py`, `compute/clustering/runner.py`.
* `select_zones.py`: composite = weighted `sil_model` + `sc_model` only. Remove any `sil_ercot`/`sc_ercot` references. Adjust CLI defaults and any config-file schema.
* `runner.py`: remove the reference-price sweep dimension; the sweep grid becomes `(algo, K)` only, fixed on `system_lambda_merit_order`. Delete/ignore the ref axis config field with a warning-on-set.
* `algorithm.py`:
  - Add `hierarchical_on_beta(beta_matrix, K, linkage="ward")` accepting β-loadings as the feature matrix.
  - Keep `hybrid_geo(...)` as-is.
  - Delete `kmeans_vec` and `pca_kmeans`. Remove their registrations in the algorithm dispatcher.
* `runner._run_cell`: fetch β-loadings from `runs/<run_id>/mapping/mapping_basis_<run_id>.npz` (bus_id → β vector — note CM.2 writes SP-level; extend CM.2 or add a sibling `mapping_basis_bus_<run_id>.npz` that also regresses **model bus** trajectories onto the components so hierarchical-on-β has per-bus features). If not present, fail fast with a clear message pointing to CM.2.
* Do NOT touch: matrix builder, mapping modules' user-facing outputs (only extend if needed), snapshot/OPF layer.

## Sections (commits)

### C1 — drop ERCOT-side scores + freeze reference axis

* `select_zones.py`: composite uses `sil_model` + `sc_model` only; delete ERCOT-side scoring code and CLI flags.
* `runner.py`: remove ref-price sweep axis; fix `ref = "system_lambda_merit_order"` and log it once.
* Update or remove ranking tests that reference dropped fields.
* Verify: `select_zones` runs on v1-120 and produces a composite table without ERCOT columns.

### C2 — β-based clustering + retire redundant algorithms

* Extend CM.2 output (or add sibling file) to include per-bus β-loadings (regress model buses onto same `F` — trivial since `F` came from `model_C`; store `betas_bus` directly).
* Add `algorithm.hierarchical_on_beta` and register it as primary.
* Delete `kmeans_vec` and `pca_kmeans`; update algorithm registry and any config surfaces that name them.
* Keep `hybrid_geo` as optional; document its role.
* Verify: sweep on v1-120 runs with `algos = [hierarchical_on_beta]` (and optionally `hybrid_geo`) and produces label CSVs.

## Acceptance

* [x] `select_zones.py` composite depends only on `sil_model` + `sc_model`.
* [x] Sweep runs against `system_lambda_merit_order` only; ref-price axis removed from config.
* [x] `hierarchical_on_beta` present and default; `kmeans_vec` and `pca_kmeans` removed.
* [x] Sweep consumes β-loadings from CM.2 output; clear error if missing.
* [x] `hybrid_geo` remains callable as fallback.
* [x] Existing tests updated; suite passes.
