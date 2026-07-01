# 0027 - refactor-sklearn

Type: refactor
Branch: refactor/0027-sklearn

## Goal

* Replace the hand-rolled ARI in `compute/congestion/compute.py` with `sklearn.metrics.adjusted_rand_score`.
* Replace `scipy.cluster.vq.kmeans2` in `split_half_cluster_stability` with `sklearn.cluster.KMeans` to match `compute/clustering/algorithm.py::kmeans_vec`.
* Drop the now-unused `scipy.cluster.vq` and `scipy.special` imports.

## Context

* sklearn is already a project dep (used in `compute/clustering/{algorithm,diagnostics}.py`); the `_adjusted_rand_score` docstring's "avoid sklearn dep" rationale is stale.
* Two remaining scipy-cluster/special call sites in `congestion/compute.py` are the only reason those imports still exist.
* `split_half_cluster_stability` shares intent with `kmeans_vec` but uses a different backend — consistency win.

## Approach

* Work in: `compute/congestion/compute.py`.
* Delete `_adjusted_rand_score` (lines ~339–361); import `adjusted_rand_score` from `sklearn.metrics` and update the sole call site in `split_half_cluster_stability` (~391).
* In `split_half_cluster_stability` (~382–393), replace both `kmeans2(..., minit='++', seed=…, missing='warn')` calls with `KMeans(n_clusters=k, n_init=1, random_state=seed+s).fit_predict(A)` (n_init=1 preserves scipy's single-init semantics; bump if more robustness wanted).
* Remove `from scipy.cluster.vq import kmeans2` and `from scipy.special import comb` at the top of the file.
* Also update `compute/clustering/diagnostics.py` import `from compute.congestion.compute import _adjusted_rand_score` (line ~20) to `from sklearn.metrics import adjusted_rand_score` and rename the call site (~84).
* Do NOT touch: `compute/clustering/algorithm.py`, any hierarchical/spectral/PCA code, `scipy.stats` or `scipy.spatial.distance` usage.

## Acceptance

* [x] `grep -rn "scipy.cluster.vq\|scipy.special\|_adjusted_rand_score\|kmeans2" compute/ --include="*.py"` returns no hits.
* [x] `docker compose run --rm compute python -m pytest /compute/clustering/tests/ -v` passes (29/29). Covers both refactored paths — `cluster_stability_ari` (KMeans + ARI) via `test_stability_kmeans`, and the sklearn ARI helper via `test_clustering.py::_ari`.
