"""
Phase 3 — clustering algorithms.

Five pure functions over a bus×hour congestion matrix `C` (rows = buses,
columns = hours). Each returns a `pd.Series` indexed by `C.index` with
integer cluster labels; buses defensively dropped (any-NaN row, or missing
coordinates for `hybrid_geo`) come back as `-1` so the downstream sweep
can detect them.

No I/O. The caller (0020 sweep) is responsible for loading the 0016 npz
and selecting a (ref_method, source) matrix.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage as scipy_linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import KMeans, SpectralClustering


def _clean(C: pd.DataFrame) -> tuple[pd.DataFrame, pd.Index]:
    """Drop rows with any NaN; return cleaned matrix and the dropped index."""
    X = C.dropna(axis=0, how="any")
    dropped = C.index.difference(X.index)
    return X, dropped


def _reindex_with_dropped(
    labels: np.ndarray, used: pd.Index, original: pd.Index, dropped: pd.Index
) -> pd.Series:
    """Build a Series over `original` with `labels` on `used` and -1 on `dropped`."""
    out = pd.Series(-1, index=original, dtype=int)
    out.loc[used] = labels.astype(int)
    return out


def hierarchical_corr(
    C: pd.DataFrame, K: int, linkage: str = "ward"
) -> pd.Series:
    """Hierarchical agglomerative clustering, cut to K clusters.

    `linkage='ward'` clusters on the raw row vectors (Euclidean — Ward
    requires it). Other linkages use correlation distance `1 - corr(C.T)`.
    """
    X, dropped = _clean(C)
    if X.shape[0] < K:
        return _reindex_with_dropped(
            np.full(X.shape[0], -1), X.index, C.index, dropped
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
    return _reindex_with_dropped(labels, X.index, C.index, dropped)


def kmeans_vec(
    C: pd.DataFrame, K: int, n_init: int = 10, seed: int = 0
) -> pd.Series:
    """K-means on raw bus row vectors."""
    X, dropped = _clean(C)
    if X.shape[0] < K:
        return _reindex_with_dropped(
            np.full(X.shape[0], -1), X.index, C.index, dropped
        )
    km = KMeans(n_clusters=K, n_init=n_init, random_state=seed)
    labels = km.fit_predict(X.to_numpy())
    return _reindex_with_dropped(labels, X.index, C.index, dropped)


def spectral_corr(
    C: pd.DataFrame, K: int, affinity: str = "abs_corr", seed: int = 0
) -> pd.Series:
    """Spectral clustering on a correlation-derived affinity matrix.

    `affinity='abs_corr'` uses `|corr(C.T)|`; `'clip_neg'` clips negatives
    to 0. Diagonal is zeroed (SpectralClustering treats it as the affinity
    matrix of a graph; self-loops are removed).
    """
    X, dropped = _clean(C)
    if X.shape[0] < K:
        return _reindex_with_dropped(
            np.full(X.shape[0], -1), X.index, C.index, dropped
        )
    R = X.T.corr().to_numpy()
    if affinity == "abs_corr":
        A = np.abs(R)
    elif affinity == "clip_neg":
        A = np.clip(R, 0.0, 1.0)
    else:
        raise ValueError(f"unknown affinity: {affinity}")
    np.fill_diagonal(A, 0.0)
    A = 0.5 * (A + A.T)
    sc = SpectralClustering(
        n_clusters=K, affinity="precomputed", random_state=seed,
        assign_labels="kmeans",
    )
    labels = sc.fit_predict(A)
    return _reindex_with_dropped(labels, X.index, C.index, dropped)


def pca_kmeans(
    C: pd.DataFrame, K: int, n_components: int = 5, seed: int = 0
) -> pd.Series:
    """PCA on the bus×hour matrix, then K-means on the top-K bus scores.

    Mirrors the SVD pattern in `congestion.py::pca_variance_explained` but
    flips orientation: there, hours are samples and buses are features
    (for hour-component analysis). Here, buses are the samples we want to
    score, so we center across buses (axis=0) and take `U * S` as PC scores.
    """
    X, dropped = _clean(C)
    if X.shape[0] < K:
        return _reindex_with_dropped(
            np.full(X.shape[0], -1), X.index, C.index, dropped
        )
    M = X.to_numpy(dtype=float)
    centered = M - M.mean(axis=0, keepdims=True)
    k = max(1, min(n_components, centered.shape[0], centered.shape[1]))
    U, S, _ = np.linalg.svd(centered, full_matrices=False)
    scores = U[:, :k] * S[:k]
    km = KMeans(n_clusters=K, n_init=10, random_state=seed)
    labels = km.fit_predict(scores)
    return _reindex_with_dropped(labels, X.index, C.index, dropped)


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
