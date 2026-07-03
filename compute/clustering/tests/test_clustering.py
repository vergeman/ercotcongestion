"""Tests for the 0017 clustering algorithm library.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/clustering/tests/test_clustering.py -v
"""
import numpy as np
import pandas as pd

from compute.clustering.algorithm import (
    hierarchical_corr,
    hierarchical_on_beta,
    hybrid_geo,
)
from sklearn.metrics import adjusted_rand_score

from .conftest import N_BUSES, N_CLUSTERS, SEED


def _ari(labels: pd.Series, truth: pd.Series) -> float:
    common = labels.index.intersection(truth.index)
    mask = labels.loc[common] >= 0
    return float(adjusted_rand_score(
        labels.loc[common][mask].to_numpy(),
        truth.loc[common][mask].to_numpy(),
    ))


def test_hierarchical_ward_recovers_planted(planted):
    C, truth = planted
    labels = hierarchical_corr(C, K=N_CLUSTERS, linkage="ward")
    assert _ari(labels, truth) > 0.9


def test_hierarchical_average_recovers_planted(planted):
    C, truth = planted
    labels = hierarchical_corr(C, K=N_CLUSTERS, linkage="average")
    assert _ari(labels, truth) > 0.9


def test_hierarchical_on_beta_recovers_planted(planted):
    """β-loadings from PCA of the planted matrix should cluster the same
    way as the raw vectors — same low-rank structure, lower dimension."""
    C, truth = planted
    # Derive per-bus β-loadings via SVD of the centered bus×hour matrix.
    M = C.to_numpy(dtype=float)
    M = M - M.mean(axis=1, keepdims=True)
    U, S, _ = np.linalg.svd(M, full_matrices=False)
    k = min(3, S.shape[0])
    betas = U[:, :k] * S[:k]
    beta_df = pd.DataFrame(betas, index=C.index)
    labels = hierarchical_on_beta(beta_df, K=N_CLUSTERS, linkage="ward")
    assert _ari(labels, truth) > 0.9


def test_hybrid_geo_smoke(planted, synthetic_coords):
    C, _ = planted
    labels = hybrid_geo(C, K=N_CLUSTERS, coords=synthetic_coords, alpha=0.3, seed=SEED)
    assert isinstance(labels, pd.Series)
    assert len(labels) == N_BUSES
    valid = labels[labels >= 0]
    assert valid.nunique() == N_CLUSTERS


def test_returns_series_indexed_on_input(planted):
    C, _ = planted
    for fn_call in [
        lambda: hierarchical_corr(C, K=N_CLUSTERS),
        lambda: hierarchical_corr(C, K=N_CLUSTERS, linkage="average"),
    ]:
        labels = fn_call()
        assert list(labels.index) == list(C.index)
        assert labels.dtype == int


def test_nan_rows_get_minus_one(planted):
    C, _ = planted
    C = C.copy()
    C.iloc[0, 0] = np.nan
    labels = hierarchical_corr(C, K=N_CLUSTERS)
    assert labels.iloc[0] == -1
    assert (labels.iloc[1:] >= 0).all()
