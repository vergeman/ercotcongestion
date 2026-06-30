"""Tests for `compute.clustering.polygons`."""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

from compute.clustering.polygons import (
    build_polygons,
    transfer_labels,
    write_zones_geojson,
)


def test_build_polygons_three_valid_polygons(planted, synthetic_coords):
    _, true_labels = planted
    p = build_polygons(true_labels, synthetic_coords)

    assert len(p) == 3
    assert set(p["cluster_id"]) == {0, 1, 2}
    assert p.crs.to_string() == "EPSG:4326"
    assert p.is_valid.all()
    assert (p["n_buses"] >= 3).all()
    assert list(p.columns) == [
        "cluster_id", "n_buses", "centroid_lat", "centroid_lon", "geometry",
    ]


def test_transfer_labels_recovers_planted(planted, synthetic_coords):
    _, true_labels = planted
    polygons = build_polygons(true_labels, synthetic_coords)

    rng = np.random.default_rng(123)
    jittered = synthetic_coords + rng.normal(0.0, 0.05, size=synthetic_coords.shape)

    recovered = transfer_labels(polygons, jittered)

    assert recovered.name == "cluster_id"
    assert recovered.dtype == int
    assert recovered.index.equals(jittered.index)
    agreement = (recovered.to_numpy() == true_labels.to_numpy()).mean()
    assert agreement > 0.95, f"only {agreement:.3f} recovered"


def test_transfer_labels_nearest_fallback(planted, synthetic_coords):
    _, true_labels = planted
    polygons = build_polygons(true_labels, synthetic_coords)

    # A point far outside any cluster polygon — should fall through to
    # nearest centroid (cluster 1 is centered near (32, -97)).
    far = pd.DataFrame(
        [[40.0, -97.0]], index=["far_north"], columns=["lat", "lon"],
    )
    out = transfer_labels(polygons, far)
    assert out.loc["far_north"] == 1


def test_geojson_round_trip(planted, synthetic_coords, tmp_path):
    _, true_labels = planted
    polygons = build_polygons(true_labels, synthetic_coords)

    out_path = tmp_path / "zones.geojson"
    write_zones_geojson(polygons, out_path)
    assert out_path.exists()

    rt = gpd.read_file(out_path)
    assert set(rt["cluster_id"]) == set(polygons["cluster_id"])

    rt_sorted = rt.sort_values("cluster_id").reset_index(drop=True)
    src_sorted = polygons.sort_values("cluster_id").reset_index(drop=True)
    for a, b in zip(rt_sorted.geometry, src_sorted.geometry):
        assert a.equals_exact(b, tolerance=1e-6)


def test_singleton_clusters_are_dropped(planted, synthetic_coords, caplog):
    _, true_labels = planted
    # Reassign two buses to a new cluster id 9 to forge a sub-3 cluster.
    forged = true_labels.copy()
    forged.iloc[[0, 1]] = 9

    with caplog.at_level(logging.INFO, logger="compute.clustering.polygons"):
        p = build_polygons(forged, synthetic_coords)

    assert 9 not in set(p["cluster_id"])
    assert any("dropping cluster" in r.message for r in caplog.records)
