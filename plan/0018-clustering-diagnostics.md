# 0018 - clustering-diagnostics

Type: feat
Branch: feat/zonal-clustering

## Context

* 0017 ships the clustering algorithm library; 0020 needs scalar quality metrics per (ref, algo, K) cell to rank them.
* No I/O, no sweep orchestration here — pure functions consumed by 0020 and unit-testable on the same planted-cluster fixture from 0017.
* Stability metric generalizes `split_half_cluster_stability` from `congestion_calculation/congestion.py`: take `algo` as a callable so any 0017 function can be evaluated.

## Goal

* Ship `compute/experiments/zonal_clustering/diagnostics.py` with four pure functions returning floats (or `pd.Series` of floats keyed by label where noted).
* Each function callable in isolation from a REPL given a bus×hour matrix and a label `pd.Series`.
* Add tests that confirm metrics behave sensibly on the 0017 planted-cluster fixture.

## Approach

* Work in: `compute/experiments/zonal_clustering/diagnostics.py` (new module in the existing 0017 package).
* Functions:
  * `silhouette(C: pd.DataFrame, labels: pd.Series) -> float` — wrap `sklearn.metrics.silhouette_score` on `C.values`. For any singleton cluster, exclude its members before scoring; if `< 2` non-singleton clusters remain, return `NaN`. Align `labels` to `C.index` first; drop rows where `labels == -1`.
  * `cluster_stability_ari(C: pd.DataFrame, algo: Callable, K: int, n_splits: int = 5, seed: int = 0, **algo_kwargs) -> float` — time-split, not random-sample. Partition hours (columns) into `n_splits` contiguous folds; for each pair of adjacent folds run `algo(C[fold_a], K, **algo_kwargs)` and `algo(C[fold_b], K, **algo_kwargs)`, compute ARI between the two label series (intersected on shared bus index, ignoring `-1`). Return mean ARI across pairs.
  * `within_cluster_variance(C: pd.DataFrame, labels: pd.Series) -> float` — sum over clusters of `sum((C_cluster - centroid)**2)`. Centroid = row-mean of cluster members. Drop `-1` labels.
  * `spatial_coherence(labels: pd.Series, coords: pd.DataFrame) -> float` — mean intra-cluster pairwise Euclidean distance ÷ mean inter-cluster pairwise distance over the `(lat, lon)` columns of `coords`. Drop buses missing from `coords` or with `-1` label. Singleton clusters contribute nothing to the intra-numerator.
* Reuse: import `_adjusted_rand_score` from `compute/experiments/congestion_calculation/congestion.py` for `cluster_stability_ari` (same as 0017 tests). Do NOT re-implement.
* Tests: `compute/experiments/zonal_clustering/tests/test_diagnostics.py`. Reuse the 0017 fixture builder (factor out into `tests/conftest.py` if not already there). Assertions on the 50-bus × 200-hour fixture with seed=0:
  * `silhouette(C, true_labels) > 0.5`.
  * `cluster_stability_ari(C, kmeans_vec, K=3) > 0.85`; same for `hierarchical_corr` and `pca_kmeans`.
  * `within_cluster_variance` decreases monotonically as K goes 2 → 3, then plateaus or rises slightly for K = 4, 5 (true K = 3).
  * `spatial_coherence(true_labels, coords) < 0.5` when synthetic coords are jittered around per-cluster centroids; `> 0.8` when coords are randomized independently of labels.
* Do NOT touch: `clustering.py`, anything under `congestion_calculation/` or `preprocess/`, I/O, JSON, npz. No sweep logic — that's 0020.

## Status

Implemented. 0017 fixtures factored into `tests/conftest.py`; `randomized_coords` fixture added there. 20/20 tests pass (`docker compose run --rm compute bash -c "pip install --quiet pytest && python -m pytest /compute/experiments/zonal_clustering/tests/ -v"`, 3.00s).

## Acceptance

* [x] `from experiments.zonal_clustering.diagnostics import silhouette, cluster_stability_ari, within_cluster_variance, spatial_coherence` succeeds.
* [x] Each function returns a `float` (or `NaN`) and tolerates label series containing `-1` without raising.
* [x] On the 50×200 planted-cluster fixture (seed=0): `silhouette > 0.5`; `cluster_stability_ari > 0.85` for `kmeans_vec`, `hierarchical_corr`, `pca_kmeans`; `within_cluster_variance` monotone non-increasing in K with sharp elbow at true K=3 (drop K=2→3 dwarfs drop K=3→4); `spatial_coherence < 0.5` on aligned coords and `> 0.8` on randomized coords.
* [x] No file or network I/O in `diagnostics.py`; functions runnable in a clean REPL after `pip install`-time deps only.
* [x] `pytest compute/experiments/zonal_clustering/tests/test_diagnostics.py` passes (12/12).
