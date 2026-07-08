"""Tests for GET /api/meta.

Every field is derived; nothing is a query param. Tests build a fake
served run tree (with the top-level ``current`` symlink) so ``run_id``
resolves via ``realpath``, write a fake scorecard for the cell params,
and queue an IBP pointer row so ``promoted_at`` populates.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from shared.settings import settings


@pytest.fixture
def served_run_dir(tmp_path, monkeypatch):
    """Build ``<runs>/current -> <runs>/v-test`` and point settings at it."""
    runs_root = tmp_path
    run_dir = runs_root / 'v-test'
    (run_dir / 'mapping').mkdir(parents=True)
    current = runs_root / 'current'
    os.symlink('v-test', current)
    monkeypatch.setattr(settings, 'served_run_dir', str(current))
    return run_dir


def _write_scorecard(run_dir: Path, ref: str, algo: str, k: int) -> None:
    (run_dir / 'mapping' / 'scorecard.json').write_text(json.dumps({
        'run_id': run_dir.name,
        'params': {'ref': ref, 'algo': algo, 'k': k, 'deadband': 2.0, 'min_members': 3},
        'headline': {'rank_spearman': 0.0, 'mean_corr': 0.0,
                     'mean_sign_agreement': 0.0, 'n_hours': 0, 'n_zones': 0},
        'zones': [],
        'warnings': [],
    }))


def test_meta_returns_full_snapshot(client, fake_pool, served_run_dir):
    _write_scorecard(served_run_dir, 'system_lambda_merit_order', 'hierarchical_on_beta', 6)
    promoted_at = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    fake_pool.cursor.queue([{'promoted_at': promoted_at}])

    r = client.get('/meta')
    assert r.status_code == 200, r.text
    body = r.json()

    assert body['run_id'] == 'v-test'
    assert body['ref'] == 'system_lambda_merit_order'
    assert body['algo'] == 'hierarchical_on_beta'
    assert body['k'] == 6
    assert body['promoted_at'].startswith('2026-04-01T12:00')


def test_meta_nulls_scorecard_fields_when_no_cell_promoted(client, fake_pool, served_run_dir):
    fake_pool.cursor.queue([])  # DB pointer unset

    r = client.get('/meta')
    assert r.status_code == 200
    body = r.json()

    # run_id still resolves — served_run_dir points at v-test even without a cell.
    assert body['run_id'] == 'v-test'
    assert body['ref'] is None
    assert body['algo'] is None
    assert body['k'] is None
    assert body['promoted_at'] is None
