"""Tests for `compute.legacy.clustering.render_partition`."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

from compute.legacy.clustering import render_partition


def _write_labels_npz(path: Path, labels: pd.Series) -> None:
    np.savez_compressed(
        path,
        bus_id=np.asarray(labels.index, dtype=np.str_),
        cluster_id=np.asarray(labels.to_numpy(), dtype=np.int64),
    )


def _write_coords_csv(path: Path, coords: pd.DataFrame) -> None:
    coords.reset_index().rename(columns={"index": "bus"}).to_csv(path, index=False)


def test_render_from_explicit_labels(planted, synthetic_coords, tmp_path):
    _, true_labels = planted
    labels_path = tmp_path / "labels.npz"
    coords_path = tmp_path / "bus_coords.csv"
    out_path = tmp_path / "zones.geojson"

    _write_labels_npz(labels_path, true_labels)
    _write_coords_csv(coords_path, synthetic_coords)

    rc = render_partition.main([
        "--labels", str(labels_path),
        "--coords-model", str(coords_path),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.exists()

    gdf = gpd.read_file(out_path)
    assert set(gdf["cluster_id"]) == {0, 1, 2}
    assert gdf.is_valid.all()


def test_render_from_run_id(planted, synthetic_coords, tmp_path, monkeypatch):
    _, true_labels = planted
    run_id = "unit-render"
    clustering_dir = tmp_path / "runs" / run_id / "clustering"
    clustering_dir.mkdir(parents=True)

    labels_path = clustering_dir / "cluster_labels_fake_ref_hierarchical_corr_k3.npz"
    _write_labels_npz(labels_path, true_labels)

    coords_path = tmp_path / "bus_coords.csv"
    _write_coords_csv(coords_path, synthetic_coords)

    monkeypatch.setattr(render_partition, "RUNS_ROOT", tmp_path / "runs")

    out_path = tmp_path / "zones.geojson"
    rc = render_partition.main([
        "--run-id", run_id,
        "--ref", "fake_ref",
        "--algo", "hierarchical_corr",
        "--k", "3",
        "--coords-model", str(coords_path),
        "--out", str(out_path),
    ])
    assert rc == 0

    gdf = gpd.read_file(out_path)
    assert len(gdf) == 3


def test_render_missing_labels_errors(tmp_path):
    coords_path = tmp_path / "coords.csv"
    coords_path.write_text("bus,lat,lon\n1,30.0,-97.0\n")
    with pytest.raises(SystemExit):
        render_partition.main([
            "--labels", str(tmp_path / "does_not_exist.npz"),
            "--coords-model", str(coords_path),
            "--out", str(tmp_path / "out.geojson"),
        ])


def test_render_requires_selectors_when_no_labels(tmp_path):
    coords_path = tmp_path / "coords.csv"
    coords_path.write_text("bus,lat,lon\n1,30.0,-97.0\n")
    with pytest.raises(SystemExit):
        render_partition.main([
            "--coords-model", str(coords_path),
            "--out", str(tmp_path / "out.geojson"),
        ])


def test_end_to_end_sweep_then_render(planted, synthetic_coords, tmp_path):
    """Sweep writes an npz; render_partition consumes it and produces a GeoJSON."""
    from compute.legacy.clustering import runner as run_clustering

    C, _ = planted
    bus_ids = list(C.index)
    n_hours = C.shape[1]

    npz_path = tmp_path / "matrices.npz"
    hours_arr = np.arange(n_hours).astype(str)
    np.savez_compressed(
        npz_path,
        ref_a_model_C=C.to_numpy(),
        ref_a_model_bus_ids=np.array(bus_ids, dtype=np.str_),
        ref_a_model_hours=hours_arr,
        ref_a_ercot_C=np.zeros((0, 0)),
        ref_a_ercot_sp_ids=np.array([], dtype="<U1"),
        ref_a_ercot_hours=np.array([], dtype="<U1"),
    )
    coords_path = tmp_path / "bus_coords.csv"
    _write_coords_csv(coords_path, synthetic_coords)

    out_dir = tmp_path / "out"
    rc = run_clustering.main([
        "--matrices", str(npz_path),
        "--coords-model", str(coords_path),
        "--out-dir", str(out_dir),
        "--ref", "ref_a",
        "--algos", "hierarchical_corr",
        "--ks", "3",
    ])
    assert rc == 0
    labels_path = out_dir / "cluster_labels_ref_a_hierarchical_corr_k3.npz"
    assert labels_path.exists()

    geojson_path = tmp_path / "zones.geojson"
    rc = render_partition.main([
        "--labels", str(labels_path),
        "--coords-model", str(coords_path),
        "--out", str(geojson_path),
    ])
    assert rc == 0
    gdf = gpd.read_file(geojson_path)
    assert len(gdf) >= 1
