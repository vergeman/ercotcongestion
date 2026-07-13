"""Shared fixtures for clustering tests."""
import numpy as np
import pandas as pd
import pytest


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


@pytest.fixture
def randomized_coords():
    """Coords drawn uniformly over the same bounding box as `synthetic_coords`
    but independent of cluster identity. Used to verify `spatial_coherence`
    reports near-1.0 when geography carries no cluster signal."""
    rng = np.random.default_rng(SEED + 42)
    arr = np.column_stack([
        rng.uniform(29.0, 32.0, size=N_BUSES),
        rng.uniform(-100.0, -95.0, size=N_BUSES),
    ])
    bus_ids = [f"bus_{i:03d}" for i in range(N_BUSES)]
    return pd.DataFrame(arr, index=bus_ids, columns=["lat", "lon"])
