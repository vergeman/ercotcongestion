"""Unit tests for GET /validation (zone-aggregated scorecard).

The endpoint reads scorecard artifacts off the runs volume, not the DB.
Tests write a fake artifact into a tmp dir, point `COMPUTE_RUNS_DIR` at
it, and assert the response mirrors the file.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import validation as validation_module


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(validation_module, 'COMPUTE_RUNS_DIR', tmp_path)
    return tmp_path


def _write_artifact(runs_dir: Path, run_id: str, algo: str, k: int) -> None:
    mdir = runs_dir / run_id / 'mapping'
    mdir.mkdir(parents=True)
    (mdir / f'scorecard_{run_id}.json').write_text(json.dumps({
        'run_id': run_id,
        'params': {
            'ref': 'system_lambda_merit_order',
            'algo': algo,
            'k': k,
            'deadband': 2.0,
            'min_members': 3,
        },
        'headline': {
            'rank_spearman': 0.42,
            'mean_corr': 0.55,
            'mean_sign_agreement': 0.71,
            'n_hours': 3,
            'n_zones': 2,
        },
        'zones': [
            {
                'cluster_id': 1, 'n_buses': 10, 'n_sps': 5,
                'corr': 0.6, 'sign_agreement': 0.75,
                'model_side_std': 0.1, 'ercot_side_std': 0.2,
                'outlier_buses': ['b_out'], 'outlier_sps': [],
            },
            {
                'cluster_id': 3, 'n_buses': 20, 'n_sps': 8,
                'corr': 0.5, 'sign_agreement': 0.67,
                'model_side_std': 0.15, 'ercot_side_std': 0.25,
                'outlier_buses': [], 'outlier_sps': ['s_out'],
            },
        ],
        'warnings': ['zone 2 dropped: n_sps=1 (< 3)'],
    }))
    np.savez_compressed(
        mdir / f'scorecard_series_{run_id}.npz',
        hours=np.array(['2026-01-01T00', '2026-01-01T01', '2026-01-01T02'], dtype=str),
        cluster_ids=np.array([1, 3], dtype=np.int64),
        model_Z=np.array([[1.0, 2.0], [1.5, 2.5], [0.5, 1.0]], dtype=float),
        ercot_Z=np.array([[1.1, 2.2], [1.4, 2.3], [0.6, 1.1]], dtype=float),
        spearman_per_hour=np.array([0.5, 0.6, 0.7], dtype=float),
    )


def test_validation_returns_scorecard(client, runs_dir):
    _write_artifact(runs_dir, 'v-test', 'hierarchical_on_beta', 6)
    r = client.get('/validation?run_id=v-test')
    assert r.status_code == 200, r.text
    body = r.json()

    assert body['run_id'] == 'v-test'
    assert body['params']['algo'] == 'hierarchical_on_beta'
    assert body['params']['k'] == 6
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


def test_validation_404_when_missing(client, runs_dir):
    r = client.get('/validation?run_id=nope')
    assert r.status_code == 404
    assert 'compute.mapping.scorecard' in r.json()['detail']


def test_validation_404_on_algo_k_mismatch(client, runs_dir):
    _write_artifact(runs_dir, 'v-test', 'hierarchical_on_beta', 6)
    r = client.get('/validation?run_id=v-test&algo=hybrid_geo&k=6')
    assert r.status_code == 404
    detail = r.json()['detail']
    assert 'algo=hierarchical_on_beta' in detail
    assert 'requested algo=hybrid_geo' in detail
