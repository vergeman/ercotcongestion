"""Unit tests for GET /validation (zone-aggregated scorecard).

The endpoint reads the served scorecard artifact off the runs volume,
not the DB. Tests build a fake ``<served_run_dir>/mapping/`` tree with
per-cell files + symlinks and point ``settings.served_run_dir`` at it.
Query params are not supported — the served cell decides everything.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from shared.settings import settings


CELL_REF = 'system_lambda_merit_order'
CELL_ALGO = 'hierarchical_on_beta'
CELL_K = 6


@pytest.fixture
def served_run_dir(tmp_path, monkeypatch):
    """A fake served run dir with the symlink layout compute.promote produces."""
    run_dir = tmp_path / 'v-test'
    (run_dir / 'mapping').mkdir(parents=True)
    monkeypatch.setattr(settings, 'served_run_dir', str(run_dir))
    return run_dir


def _write_artifact(run_dir: Path, run_id: str, ref: str, algo: str, k: int) -> None:
    mdir = run_dir / 'mapping'
    cell = f'{run_id}_{ref}_{algo}_k{k}'
    (mdir / f'scorecard_{cell}.json').write_text(json.dumps({
        'run_id': run_id,
        'params': {
            'ref': ref, 'algo': algo, 'k': k,
            'deadband': 2.0, 'min_members': 3,
        },
        'headline': {
            'rank_spearman': 0.42, 'mean_corr': 0.55,
            'mean_sign_agreement': 0.71, 'n_hours': 3, 'n_zones': 2,
        },
        'zones': [
            {'cluster_id': 1, 'n_buses': 10, 'n_sps': 5,
             'corr': 0.6, 'sign_agreement': 0.75,
             'model_side_std': 0.1, 'ercot_side_std': 0.2,
             'outlier_buses': ['b_out'], 'outlier_sps': []},
            {'cluster_id': 3, 'n_buses': 20, 'n_sps': 8,
             'corr': 0.5, 'sign_agreement': 0.67,
             'model_side_std': 0.15, 'ercot_side_std': 0.25,
             'outlier_buses': [], 'outlier_sps': ['s_out']},
        ],
        'warnings': ['zone 2 dropped: n_sps=1 (< 3)'],
    }))
    np.savez_compressed(
        mdir / f'scorecard_series_{cell}.npz',
        hours=np.array(['2026-01-01T00', '2026-01-01T01', '2026-01-01T02'], dtype=str),
        cluster_ids=np.array([1, 3], dtype=np.int64),
        model_Z=np.array([[1.0, 2.0], [1.5, 2.5], [0.5, 1.0]], dtype=float),
        ercot_Z=np.array([[1.1, 2.2], [1.4, 2.3], [0.6, 1.1]], dtype=float),
        spearman_per_hour=np.array([0.5, 0.6, 0.7], dtype=float),
    )
    # Symlinks compute.promote flips: plain-name reads no matter which cell.
    os.symlink(f'scorecard_{cell}.json', mdir / 'scorecard.json')
    os.symlink(f'scorecard_series_{cell}.npz', mdir / 'scorecard_series.npz')


def test_validation_returns_served_scorecard(client, served_run_dir):
    _write_artifact(served_run_dir, 'v-test', CELL_REF, CELL_ALGO, CELL_K)
    r = client.get('/validation')
    assert r.status_code == 200, r.text
    body = r.json()

    assert body['run_id'] == 'v-test'
    assert body['params']['ref'] == CELL_REF
    assert body['params']['algo'] == CELL_ALGO
    assert body['params']['k'] == CELL_K
    assert body['headline']['n_zones'] == 2
    assert body['headline']['rank_spearman'] == 0.42
    assert body['warnings'] == ['zone 2 dropped: n_sps=1 (< 3)']

    zones = body['zones']
    assert [z['cluster_id'] for z in zones] == [1, 3]
    assert zones[0]['outlier_buses'] == ['b_out']

    series = body['series']
    assert series['cluster_ids'] == [1, 3]
    assert len(series['hours']) == 3
    assert series['model_Z'][0] == [1.0, 2.0]


def test_validation_ignores_stray_query_params(client, served_run_dir):
    """FastAPI ignores unknown query params by default; the endpoint takes none."""
    _write_artifact(served_run_dir, 'v-test', CELL_REF, CELL_ALGO, CELL_K)
    r = client.get('/validation?run_id=other&algo=hybrid_geo&k=99')
    assert r.status_code == 200
    body = r.json()
    assert body['run_id'] == 'v-test'
    assert body['params']['algo'] == CELL_ALGO


def test_validation_503_when_no_scorecard_served(client, served_run_dir):
    r = client.get('/validation')
    assert r.status_code == 503
    assert 'compute.promote' in r.json()['detail']
