"""Tests for the 0017 clustering algorithm library.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/experiments/zonal_clustering/tests/test_clustering.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, "/compute")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
import pytest

from experiments.zonal_clustering.clustering import (
    hierarchical_corr,
    hybrid_geo,
    kmeans_vec,
    pca_kmeans,
    spectral_corr,
)
from experiments.congestion_calculation.congestion import _adjusted_rand_score


N_BUSES = 50
N_HOURS = 200
N_CLUSTERS = 3
SEED = 0


@pytest.fixture
def planted():
    """50 buses × 200 hours, 3 planted clusters sharing a common base series
    plus small Gaussian per-bus noise. Returns (C, true_labels)."""
    rng = np.random.default_rng(SEED)
    per_cluster = N_BUSES // N_CLUSTERS
    true_labels = np.concatenate([
        np.full(per_cluster, k) for k in range(N_CLUSTERS)
    ])
    # Pad to exactly N_BUSES, assigning leftovers to the last cluster.
    if true_labels.size < N_BUSES:
        true_labels = np.concatenate([
            true_labels,
            np.full(N_BUSES - true_labels.size, N_CLUSTERS - 1),
        ])

    bases = rng.normal(0.0, 1.0, size=(N_CLUSTERS, N_HOURS))
    noise = rng.normal(0.0, 0.1, size=(N_BUSES, N_HOURS))
    M = bases[true_labels] + noise

    bus_ids = [f"bus_{i:03d}" for i in range(N_BUSES)]
    cols = pd.date_range("2026-01-01", periods=N_HOURS, freq="h")
    C = pd.DataFrame(M, index=bus_ids, columns=cols)
    return C, pd.Series(true_labels, index=bus_ids)


@pytest.fixture
def synthetic_coords():
    """Coords that mirror cluster identity — three loose geographic blobs."""
    rng = np.random.default_rng(SEED + 1)
    per_cluster = N_BUSES // N_CLUSTERS
    centers = np.array([[30.0, -100.0], [32.0, -97.0], [29.0, -95.0]])
    pts = []
    for k in range(N_CLUSTERS):
        n = per_cluster + (N_BUSES - per_cluster * N_CLUSTERS if k == N_CLUSTERS - 1 else 0)
        pts.append(centers[k] + rng.normal(0.0, 0.3, size=(n, 2)))
    arr = np.concatenate(pts, axis=0)
    bus_ids = [f"bus_{i:03d}" for i in range(N_BUSES)]
    return pd.DataFrame(arr, index=bus_ids, columns=["lat", "lon"])


def _ari(labels: pd.Series, truth: pd.Series) -> float:
    common = labels.index.intersection(truth.index)
    mask = labels.loc[common] >= 0
    return _adjusted_rand_score(
        labels.loc[common][mask].to_numpy(),
        truth.loc[common][mask].to_numpy(),
    )


def test_hierarchical_ward_recovers_planted(planted):
    C, truth = planted
    labels = hierarchical_corr(C, K=N_CLUSTERS, linkage="ward")
    assert _ari(labels, truth) > 0.9


def test_hierarchical_average_recovers_planted(planted):
    C, truth = planted
    labels = hierarchical_corr(C, K=N_CLUSTERS, linkage="average")
    assert _ari(labels, truth) > 0.9


def test_kmeans_vec_recovers_planted(planted):
    C, truth = planted
    labels = kmeans_vec(C, K=N_CLUSTERS, seed=SEED)
    assert _ari(labels, truth) > 0.9


def test_pca_kmeans_recovers_planted(planted):
    C, truth = planted
    labels = pca_kmeans(C, K=N_CLUSTERS, n_components=5, seed=SEED)
    assert _ari(labels, truth) > 0.9


def test_spectral_corr_smoke(planted):
    C, _ = planted
    labels = spectral_corr(C, K=N_CLUSTERS, affinity="abs_corr", seed=SEED)
    assert isinstance(labels, pd.Series)
    assert len(labels) == N_BUSES
    valid = labels[labels >= 0]
    assert valid.nunique() == N_CLUSTERS


def test_hybrid_geo_smoke(planted, synthetic_coords):
    C, _ = planted
    labels = hybrid_geo(C, K=N_CLUSTERS, coords=synthetic_coords, alpha=0.3, seed=SEED)
    assert isinstance(labels, pd.Series)
    assert len(labels) == N_BUSES
    valid = labels[labels >= 0]
    assert valid.nunique() == N_CLUSTERS


def test_returns_series_indexed_on_C(planted):
    C, _ = planted
    for fn_call in [
        lambda: hierarchical_corr(C, K=N_CLUSTERS),
        lambda: kmeans_vec(C, K=N_CLUSTERS),
        lambda: pca_kmeans(C, K=N_CLUSTERS),
    ]:
        labels = fn_call()
        assert list(labels.index) == list(C.index)
        assert labels.dtype == int


def test_nan_rows_get_minus_one(planted):
    C, _ = planted
    C = C.copy()
    C.iloc[0, 0] = np.nan
    labels = kmeans_vec(C, K=N_CLUSTERS, seed=SEED)
    assert labels.iloc[0] == -1
    assert (labels.iloc[1:] >= 0).all()
