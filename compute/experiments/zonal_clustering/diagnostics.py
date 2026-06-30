"""Clustering diagnostics.

Pure functions over a bus×hour matrix and/or a label series. No I/O.

`cluster_stability_ari` is the only one that drives clustering itself — it
takes a clustering algo as a callable and runs it on contiguous time folds of
`C`, returning the mean adjacent-fold ARI.

"""
from __future__ import annotations

import inspect
from typing import Callable

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from sklearn.metrics import silhouette_score as _sk_silhouette

from experiments.congestion_calculation.congestion import _adjusted_rand_score


def _align_labels(C: pd.DataFrame, labels: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """Restrict (C, labels) to rows present in both and drop -1 labels."""
    common = C.index.intersection(labels.index)
    L = labels.loc[common]
    L = L[L >= 0]
    return C.loc[L.index], L


def silhouette(C: pd.DataFrame, labels: pd.Series) -> float:
    """Mean silhouette score over non-singleton clusters.

    Singleton-cluster members are excluded before scoring (sklearn would
    otherwise either error or weight a meaningless 0). Returns NaN if
    fewer than two non-singleton clusters survive.
    """
    X, L = _align_labels(C, labels)
    sizes = L.value_counts()
    keep_clusters = sizes[sizes >= 2].index
    mask = L.isin(keep_clusters)
    X = X.loc[mask]
    L = L.loc[mask]
    if L.nunique() < 2 or len(L) < 2:
        return float("nan")
    return float(_sk_silhouette(X.to_numpy(), L.to_numpy()))


def cluster_stability_ari(
    C: pd.DataFrame,
    algo: Callable,
    K: int,
    n_splits: int = 5,
    seed: int = 0,
    **algo_kwargs,
) -> float:
    """Mean ARI between labels produced on adjacent contiguous time folds.

    Columns of `C` are partitioned into `n_splits` contiguous folds. For
    each adjacent pair the supplied `algo` is run on both folds and the
    label series are compared on their common (non-dropped) bus index.

    `seed` is forwarded into `algo_kwargs` only if `algo` declares a
    `seed` parameter and the caller hasn't already set one.
    """
    if n_splits < 2 or C.shape[1] < n_splits:
        return float("nan")

    sig = inspect.signature(algo)
    if "seed" in sig.parameters and "seed" not in algo_kwargs:
        algo_kwargs["seed"] = seed

    folds = np.array_split(np.arange(C.shape[1]), n_splits)
    aris: list[float] = []
    for a_idx, b_idx in zip(folds[:-1], folds[1:]):
        A = C.iloc[:, a_idx]
        B = C.iloc[:, b_idx]
        la = algo(A, K, **algo_kwargs)
        lb = algo(B, K, **algo_kwargs)
        common = la.index.intersection(lb.index)
        mask = (la.loc[common] >= 0) & (lb.loc[common] >= 0)
        if mask.sum() < 2:
            continue
        ari = _adjusted_rand_score(
            la.loc[common][mask].to_numpy(),
            lb.loc[common][mask].to_numpy(),
        )
        if not np.isnan(ari):
            aris.append(ari)

    if not aris:
        return float("nan")
    return float(np.mean(aris))


def within_cluster_variance(C: pd.DataFrame, labels: pd.Series) -> float:
    """Sum of squared deviations from per-cluster centroids.

    Standard k-means objective. Useful for elbow/knee detection across K.
    """
    X, L = _align_labels(C, labels)
    if X.empty:
        return float("nan")
    total = 0.0
    for k in L.unique():
        members = X.loc[L == k].to_numpy(dtype=float)
        centroid = members.mean(axis=0, keepdims=True)
        total += float(((members - centroid) ** 2).sum())
    return total


def spatial_coherence(labels: pd.Series, coords: pd.DataFrame) -> float:
    """Mean intra-cluster pairwise distance ÷ mean inter-cluster pairwise distance.

    Smaller = clusters are geographically contiguous. Returns NaN if
    either numerator or denominator has no contributing pairs (e.g. all
    points share one cluster, or every cluster is a singleton).
    """
    common = labels.index.intersection(coords.index)
    L = labels.loc[common]
    L = L[L >= 0]
    pts = coords.loc[L.index].dropna()
    L = L.loc[pts.index]
    if len(pts) < 2 or L.nunique() < 2:
        return float("nan")

    D = squareform(pdist(pts.to_numpy(dtype=float)))
    n = len(pts)
    i, j = np.triu_indices(n, k=1)
    lvals = L.to_numpy()
    same = lvals[i] == lvals[j]
    if not same.any() or not (~same).any():
        return float("nan")
    intra = D[i, j][same].mean()
    inter = D[i, j][~same].mean()
    if inter == 0:
        return float("nan")
    return float(intra / inter)
