# 0017 - clustering-algorithms

Type: feat
Branch: feat/zonal-clustering

## Context

Phase 3 of the ERCOT/PyPSA congestion comparison derives behavioral zones from the bus×hour congestion matrices persisted by 0016. The downstream sweep (0020) needs to call multiple clustering algorithms uniformly. This sprint ships the algorithm library — pure functions only — so 0018 (diagnostics) and 0020 (sweep) can be developed against a stable interface.

## Goal

* Ship `compute/experiments/zonal_clustering/clustering.py` with five pure clustering functions returning `pd.Series` (index = bus_id, values = int cluster label).
* Each function callable in isolation from a REPL given a bus×hour matrix recovered from the 0016 npz.
* Add a test fixture + tests that confirm the three baseline algos recover planted clusters at ARI > 0.9.

## Approach

* Work in: `compute/experiments/zonal_clustering/` (new package; add `__init__.py`).
* Primary module: `compute/experiments/zonal_clustering/clustering.py`.
* Common signature: `fn(C: pd.DataFrame, K: int, **kwargs) -> pd.Series[int]` where `C` is bus×hour (rows = buses, columns = hours), already NaN-cleaned by the caller. Rows with any NaN are dropped defensively inside each function; result is reindexed to the original `C.index` with `-1` for dropped rows so the sweep can detect them.
* Functions:
  * `hierarchical_corr(C, K, linkage='ward')` — distance = `1 - corr(C.T)`; use `scipy.cluster.hierarchy.linkage` (condensed distance via `scipy.spatial.distance.squareform`) + `fcluster(..., t=K, criterion='maxclust')`. Ward needs Euclidean; when `linkage='ward'`, cluster on the row vectors directly (Euclidean), else on correlation distance.
  * `kmeans_vec(C, K, n_init=10, seed=0)` — `sklearn.cluster.KMeans(n_clusters=K, n_init=n_init, random_state=seed)` on `C.values`.
  * `spectral_corr(C, K, affinity='abs_corr')` — build affinity from `C.T.corr()`; `abs_corr` → `|R|`, `clip_neg` → `R.clip(lower=0)`; zero the diagonal; `sklearn.cluster.SpectralClustering(n_clusters=K, affinity='precomputed', random_state=seed)`.
  * `pca_kmeans(C, K, n_components=5, seed=0)` — center rows, SVD via `np.linalg.svd` (mirror the pattern in `congestion.py::pca_variance_explained`), take top-`n_components` bus loadings as features, then `KMeans` on those. Re-using SVD avoids adding a sklearn PCA dependency we don't already have.
  * `hybrid_geo(C, K, coords, alpha=0.3, seed=0)` — `coords` is a `pd.DataFrame[bus_id -> (lat, lon)]`. Standardize `C` rows and `coords` separately (z-score), concatenate as `[C_z | alpha * coords_z]`, then `KMeans`. Drop buses missing from `coords`; reindex same as other fns.
* Reuse: do NOT re-implement ARI here — `compute/experiments/congestion_calculation/congestion.py::_adjusted_rand_score` already exists and the test will import it.
* Tests: `compute/experiments/zonal_clustering/tests/test_clustering.py`. Fixture builds a 50-bus × 200-hour matrix with 3 planted clusters: each cluster shares a base time-series + small Gaussian noise (seeded). Assert ARI > 0.9 for `hierarchical_corr` (both `ward` and `average`), `kmeans_vec`, `pca_kmeans`. Smoke tests for `spectral_corr` and `hybrid_geo`: returns a `pd.Series` of length 50 with exactly `K` unique labels (ignoring `-1`).
* Do NOT touch: anything under `congestion_calculation/`, `preprocess/`, or any I/O. No CLI, no JSON, no npz read in this sprint — the test fabricates the matrix in-memory. Sweep-level loading of the 0016 npz lives in 0020.

## Status

Implemented. `scikit-learn` added to `Dockerfile`. 8/8 tests pass (`pytest /compute/experiments/zonal_clustering/tests/test_clustering.py`, 2.45s).

## Acceptance

* [x] `from experiments.zonal_clustering.clustering import hierarchical_corr, kmeans_vec, spectral_corr, pca_kmeans, hybrid_geo` succeeds.
* [x] Each function returns a `pd.Series` indexed by `C.index`, dtype int (with `-1` for any defensively dropped bus), with `<= K` distinct non-negative labels.
* [x] On the 50×200 planted-cluster fixture (seed=0): ARI > 0.9 for `hierarchical_corr(linkage='ward')`, `hierarchical_corr(linkage='average')`, `kmeans_vec`, `pca_kmeans`.
* [x] `spectral_corr` and `hybrid_geo` smoke-pass: correct length, correct label count, no exceptions on the fixture (with synthetic coords for `hybrid_geo`).
* [x] No file or network I/O in `clustering.py`; functions importable and runnable in a clean REPL after `pip install`-time deps only.
