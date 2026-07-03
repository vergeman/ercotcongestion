"""Tests for `compute.clustering.runner` and `select_zones`.

Run inside the compute container::

    docker compose run --rm compute python -m pytest \
        /compute/clustering/tests/test_run_clustering.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.clustering import runner as run_clustering, select_zones


# ---------------------------------------------------------------------------
# Fixtures: a 2-ref npz (one full, one ercot-empty) + matching coord CSVs.
# ---------------------------------------------------------------------------

N_BUSES = 12
N_SPS = 8
N_HOURS = 60
N_CLUSTERS = 3
SEED = 0


def _planted_matrix(n_rows: int, ids: list[str], n_hours: int, seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    per = n_rows // N_CLUSTERS
    labels = np.concatenate([
        np.full(per, k) for k in range(N_CLUSTERS)
    ])
    if labels.size < n_rows:
        labels = np.concatenate([labels, np.full(n_rows - labels.size, N_CLUSTERS - 1)])
    bases = rng.normal(0.0, 1.0, size=(N_CLUSTERS, n_hours))
    noise = rng.normal(0.0, 0.05, size=(n_rows, n_hours))
    M = bases[labels] + noise
    hours = np.array([f"regime|2026-01-01T{h:02d}:00:00+00:00" for h in range(n_hours)])
    return pd.DataFrame(M, index=ids, columns=hours), labels


@pytest.fixture
def sweep_inputs(tmp_path: Path) -> dict[str, Path]:
    bus_ids = [f"{1000 + i}" for i in range(N_BUSES)]
    sp_ids = [f"SP_{i:03d}" for i in range(N_SPS)]

    C_model, model_labels = _planted_matrix(N_BUSES, bus_ids, N_HOURS, SEED)
    C_ercot, _ = _planted_matrix(N_SPS, sp_ids, N_HOURS, SEED + 1)

    # Coords aligned with cluster identity for both sides.
    rng = np.random.default_rng(SEED + 2)
    centers = np.array([[30.0, -100.0], [32.0, -97.0], [29.0, -95.0]])
    model_coords = pd.DataFrame(
        {
            "bus": bus_ids,
            "lat": centers[model_labels, 0] + rng.normal(0, 0.2, N_BUSES),
            "lon": centers[model_labels, 1] + rng.normal(0, 0.2, N_BUSES),
        }
    )
    # ERCOT SPs placed inside the model hull, evenly across the three centers.
    sp_labels = np.array([i % N_CLUSTERS for i in range(N_SPS)])
    ercot_coords = pd.DataFrame(
        {
            "settlement_point": sp_ids,
            "lat": centers[sp_labels, 0] + rng.normal(0, 0.2, N_SPS),
            "lon": centers[sp_labels, 1] + rng.normal(0, 0.2, N_SPS),
        }
    )

    coords_model_path = tmp_path / "bus_coords.csv"
    coords_ercot_path = tmp_path / "sp_coords.csv"
    model_coords.to_csv(coords_model_path, index=False)
    ercot_coords.to_csv(coords_ercot_path, index=False)

    # Build the npz: ref `fake_a` is two-sided; ref `fake_b` has empty ercot
    # (mimicking system_lambda_kkt — model-only).
    npz_path = tmp_path / "congestion_matrices_unit.npz"
    hours_arr = np.array(list(C_model.columns), dtype=np.str_)
    bus_ids_arr = np.array(bus_ids, dtype=np.str_)
    sp_ids_arr = np.array(sp_ids, dtype=np.str_)
    arrays = {
        "fake_a_model_C": C_model.to_numpy(),
        "fake_a_model_bus_ids": bus_ids_arr,
        "fake_a_model_hours": hours_arr,
        "fake_a_ercot_C": C_ercot.to_numpy(),
        "fake_a_ercot_sp_ids": sp_ids_arr,
        "fake_a_ercot_hours": hours_arr,
        "fake_b_model_C": C_model.to_numpy(),
        "fake_b_model_bus_ids": bus_ids_arr,
        "fake_b_model_hours": hours_arr,
        "fake_b_ercot_C": np.zeros((0, 0)),
        "fake_b_ercot_sp_ids": np.array([], dtype="<U1"),
        "fake_b_ercot_hours": np.array([], dtype="<U1"),
    }
    np.savez_compressed(npz_path, **arrays)

    return {
        "npz": npz_path,
        "coords_model": coords_model_path,
        "coords_ercot": coords_ercot_path,
        "out_dir": tmp_path / "out",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _argv(sweep_inputs: dict[str, Path], algos: str, ks: str, refs: str | None = None) -> list[str]:
    argv = [
        "--matrices", str(sweep_inputs["npz"]),
        "--coords-model", str(sweep_inputs["coords_model"]),
        "--out-dir", str(sweep_inputs["out_dir"]),
        "--algos", algos,
        "--ks", ks,
    ]
    if refs is not None:
        argv += ["--ref-methods", refs]
    return argv


def test_sweep_emits_summary_and_per_cell_artifacts(sweep_inputs):
    rc = run_clustering.main(
        _argv(sweep_inputs, algos="kmeans_vec,hierarchical_corr", ks="3"),
    )
    assert rc == 0

    out_dir = sweep_inputs["out_dir"]
    summary_path = out_dir / "clustering_summary_unit.json"
    assert summary_path.exists()

    with summary_path.open() as f:
        summary = json.load(f)

    rows = summary["rows"]
    df = pd.DataFrame(rows)

    # 2 refs × 2 algos × 1 K = 4 rows.
    assert len(df) == 4
    assert set(df["ref"]) == {"fake_a", "fake_b"}
    assert set(df["algo"]) == {"kmeans_vec", "hierarchical_corr"}
    assert (df["status"] == "ok").all()

    # Every ok cell writes a labels npz; polygons are no longer emitted here.
    for r in rows:
        labels_path = out_dir / f"cluster_labels_{r['ref']}_{r['algo']}_k{r['K']}.npz"
        assert labels_path.exists(), f"missing {labels_path}"
        with np.load(labels_path, allow_pickle=False) as z:
            assert set(z.files) == {"bus_id", "cluster_id"}
            assert z["bus_id"].shape == z["cluster_id"].shape
            assert z["bus_id"].shape[0] == r["n_buses_model"]

        gj = out_dir / f"zones_{r['ref']}_{r['algo']}_k{r['K']}.geojson"
        assert not gj.exists(), f"unexpected geojson: {gj}"

    # ERCOT-side artifacts are no longer emitted (CM.4 retires geo transfer
    # from the sweep path — behavioral mapping happens in compute/mapping).
    for r in rows:
        csv = out_dir / f"ercot_sp_labels_{r['ref']}_{r['algo']}_k{r['K']}.csv"
        assert not csv.exists()
        assert "sil_ercot" not in r
        assert "sc_ercot" not in r
        assert "n_sps_ercot" not in r
        assert "n_polygons" not in r


def test_sweep_skips_empty_ercot_silently(sweep_inputs, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="compute.clustering.runner"):
        rc = run_clustering.main(
            _argv(sweep_inputs, algos="kmeans_vec", ks="3", refs="fake_b"),
        )
    assert rc == 0
    # The empty ercot side is logged as SKIP, not as a failed cell.
    assert any("SKIP fake_b/ercot" in r.message for r in caplog.records)

    summary = json.loads(
        (sweep_inputs["out_dir"] / "clustering_summary_unit.json").read_text(),
    )
    # 1 ref × 1 algo × 1 K. Sweep no longer touches the ERCOT side.
    assert len(summary["rows"]) == 1
    assert summary["rows"][0]["status"] == "ok"


def test_failed_algo_records_failed_status(sweep_inputs, monkeypatch):
    """An algo that raises produces a status=failed row, no GeoJSON, no crash."""
    def boom(C, K, **kwargs):
        raise RuntimeError("intentional")

    monkeypatch.setitem(run_clustering.ALGOS, "kmeans_vec", boom)

    rc = run_clustering.main(
        _argv(sweep_inputs, algos="kmeans_vec", ks="3", refs="fake_a"),
    )
    assert rc == 0

    out_dir = sweep_inputs["out_dir"]
    summary = json.loads(
        (out_dir / "clustering_summary_unit.json").read_text(),
    )
    assert len(summary["rows"]) == 1
    row = summary["rows"][0]
    assert row["status"] == "failed"
    assert "RuntimeError" in row["error"]
    assert not (out_dir / "zones_fake_a_kmeans_vec_k3.geojson").exists()
    assert not (out_dir / "cluster_labels_fake_a_kmeans_vec_k3.npz").exists()


def test_select_zones_ranks_and_runs(sweep_inputs, capsys):
    run_clustering.main(
        _argv(sweep_inputs, algos="kmeans_vec,hierarchical_corr", ks="3"),
    )
    summary_path = sweep_inputs["out_dir"] / "clustering_summary_unit.json"

    rc = select_zones.main(["--summary", str(summary_path), "--top", "10"])
    assert rc == 0
    out = capsys.readouterr().out
    # Header present, four rows printed.
    assert "rank" in out and "score" in out
    # Ranks 1..4 should appear.
    for k in range(1, 5):
        assert f" {k} " in out or out.lstrip().startswith(f"{k} ")
