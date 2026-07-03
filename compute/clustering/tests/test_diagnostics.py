"""Tests for the 0018 clustering diagnostics library.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \
        /compute/clustering/tests/test_diagnostics.py -v
"""
import numpy as np
import pandas as pd

from compute.clustering.algorithm import (
    hierarchical_corr,
    hierarchical_on_beta,
)
from compute.clustering.diagnostics import (
    cluster_stability_ari,
    silhouette,
    spatial_coherence,
    within_cluster_variance,
)

from .conftest import N_BUSES, N_CLUSTERS, SEED


def test_silhouette_on_true_labels(planted):
    C, truth = planted
    assert silhouette(C, truth) > 0.5


def test_silhouette_handles_minus_one(planted):
    C, truth = planted
    labels = truth.copy()
    labels.iloc[0] = -1
    val = silhouette(C, labels)
    assert not np.isnan(val) and val > 0.5


def test_silhouette_singleton_excluded(planted):
    C, truth = planted
    # Build labels with one singleton cluster (label=99 on a single bus)
    labels = truth.copy()
    labels.iloc[0] = 99
    val = silhouette(C, labels)
    assert not np.isnan(val) and val > 0.5


def test_stability_hierarchical_ward(planted):
    C, _ = planted
    ari = cluster_stability_ari(
        C, hierarchical_corr, K=N_CLUSTERS, n_splits=5, linkage="ward"
    )
    assert ari > 0.85


def test_stability_hierarchical_average(planted):
    C, _ = planted
    ari = cluster_stability_ari(
        C, hierarchical_corr, K=N_CLUSTERS, n_splits=5, linkage="average"
    )
    assert ari > 0.85


def test_within_cluster_variance_elbow_at_true_k(planted):
    C, _ = planted
    wcv = {
        k: within_cluster_variance(C, hierarchical_corr(C, K=k, linkage="ward"))
        for k in (2, 3, 4, 5)
    }
    # Monotone non-increasing in K (more clusters → at least as tight).
    assert wcv[2] >= wcv[3] >= wcv[4] >= wcv[5]
    # Sharp drop K=2→3 (crossing the true K) dwarfs drop K=3→4 (overfitting).
    drop_2_3 = wcv[2] - wcv[3]
    drop_3_4 = wcv[3] - wcv[4]
    assert drop_2_3 > 5 * drop_3_4


def test_within_cluster_variance_drops_minus_one(planted):
    C, truth = planted
    labels = truth.copy()
    labels.iloc[0] = -1
    full = within_cluster_variance(C, truth)
    partial = within_cluster_variance(C, labels)
    # Dropping a near-centroid point can only decrease total WCV.
    assert partial <= full + 1e-9


def test_spatial_coherence_aligned_low(planted, synthetic_coords):
    _, truth = planted
    assert spatial_coherence(truth, synthetic_coords) < 0.5


def test_spatial_coherence_random_high(planted, randomized_coords):
    _, truth = planted
    assert spatial_coherence(truth, randomized_coords) > 0.8


def test_spatial_coherence_handles_minus_one(planted, synthetic_coords):
    _, truth = planted
    labels = truth.copy()
    labels.iloc[0] = -1
    val = spatial_coherence(labels, synthetic_coords)
    assert not np.isnan(val) and val < 0.5


def test_spatial_coherence_single_cluster_nan(planted, synthetic_coords):
    _, truth = planted
    labels = pd.Series(0, index=truth.index)
    assert np.isnan(spatial_coherence(labels, synthetic_coords))
