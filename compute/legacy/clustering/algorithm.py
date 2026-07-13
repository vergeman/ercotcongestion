"""Clustering algorithms.

Three pure functions over a feature matrix `F` (rows = buses; columns =
either hours for raw-vector algos, or β components for
`hierarchical_on_beta`). Each returns a `pd.Series` indexed by `F.index`
with integer cluster labels; buses defensively dropped (any-NaN row, or
missing coordinates for `hybrid_geo`) come back as `-1` so the downstream
sweep can detect them.

Algorithm inventory (post-CM.6):

* `hierarchical_on_beta` — primary. Ward-linked hierarchical clustering
  on Stage-B β-loadings from `compute.legacy.mapping.basis_regression`. Aligns
  clustering with the translation-invariant metric introduced in CM.2.
* `hybrid_geo` — optional fallback. K-means on `[z(C) | α·z(coords)]`.
* `hierarchical_corr` — legacy raw-vector hierarchical clustering.

`kmeans_vec` and `pca_kmeans` were retired in CM.6.

No I/O. The caller is responsible for loading the npz and selecting a
feature matrix.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage as scipy_linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import KMeans


def _clean(F: pd.DataFrame) -> tuple[pd.DataFrame, pd.Index]:
    """Drop rows with any NaN; return cleaned matrix and the dropped index."""
    X = F.dropna(axis=0, how="any")
    dropped = F.index.difference(X.index)
    return X, dropped


def _reindex_with_dropped(
    labels: np.ndarray, used: pd.Index, original: pd.Index, dropped: pd.Index
) -> pd.Series:
    """Build a Series over `original` with `labels` on `used` and -1 on `dropped`."""
    out = pd.Series(-1, index=original, dtype=int)
    out.loc[used] = labels.astype(int)
    return out


def _hierarchical(
    F: pd.DataFrame, K: int, linkage: str = "ward"
) -> pd.Series:
    """Shared Ward / correlation-distance hierarchical clustering."""
    X, dropped = _clean(F)
    if X.shape[0] < K:
        return _reindex_with_dropped(
            np.full(X.shape[0], -1), X.index, F.index, dropped
        )

    if linkage == "ward":
        Z = scipy_linkage(X.to_numpy(), method="ward")
    else:
        R = X.T.corr().to_numpy()
        D = np.clip(1.0 - R, 0.0, 2.0)
        np.fill_diagonal(D, 0.0)
        D = 0.5 * (D + D.T)
        Z = scipy_linkage(squareform(D, checks=False), method=linkage)

    labels = fcluster(Z, t=K, criterion="maxclust")
    return _reindex_with_dropped(labels, X.index, F.index, dropped)


def hierarchical_corr(
    C: pd.DataFrame, K: int, linkage: str = "ward"
) -> pd.Series:
    """Hierarchical agglomerative clustering on the raw bus×hour matrix.

    `linkage='ward'` clusters on the raw row vectors (Euclidean — Ward
    requires it). Other linkages use correlation distance `1 - corr(C.T)`.
    """
    return _hierarchical(C, K, linkage=linkage)


def hierarchical_on_beta(
    beta_matrix: pd.DataFrame, K: int, linkage: str = "ward"
) -> pd.Series:
    """Hierarchical agglomerative clustering on Stage-B β-loadings.

    `beta_matrix` is a DataFrame of shape (n_bus, k) whose rows are the
    per-bus β-coefficients from CM.2 basis regression (bus_id → β
    vector). β-space is a lower-dimensional, denoised representation of
    each bus's temporal behavior, so clustering here aligns with the
    translation-invariant metric introduced in CM.2/CM.3.
    """
    return _hierarchical(beta_matrix, K, linkage=linkage)


def hybrid_geo(
    C: pd.DataFrame,
    K: int,
    coords: pd.DataFrame,
    alpha: float = 0.3,
    seed: int = 0,
) -> pd.Series:
    """K-means on `[z(C) | alpha * z(coords)]`.

    `coords` is `pd.DataFrame[bus_id -> (lat, lon)]`. Buses present in `C`
    but missing from `coords` are dropped (labeled -1) — geographic
    weighting only makes sense for buses we can locate.
    """
    X, dropped_nan = _clean(C)
    coords = coords.reindex(X.index)
    missing_coords = coords.index[coords.isna().any(axis=1)]
    X = X.drop(index=missing_coords)
    coords = coords.drop(index=missing_coords)
    dropped = C.index.difference(X.index)

    if X.shape[0] < K:
        return _reindex_with_dropped(
            np.full(X.shape[0], -1), X.index, C.index, dropped
        )

    def _zscore(A: np.ndarray) -> np.ndarray:
        mu = A.mean(axis=0, keepdims=True)
        sd = A.std(axis=0, keepdims=True)
        sd = np.where(sd > 0, sd, 1.0)
        return (A - mu) / sd

    Xz = _zscore(X.to_numpy(dtype=float))
    Cz = _zscore(coords.to_numpy(dtype=float))
    feats = np.concatenate([Xz, alpha * Cz], axis=1)
    km = KMeans(n_clusters=K, n_init=10, random_state=seed)
    labels = km.fit_predict(feats)
    return _reindex_with_dropped(labels, X.index, C.index, dropped)
