"""Schema regression guard.

Locks in:
  * `BusState` and `SnapshotMeta` field names.
  * Zone-aggregated `ScorecardResponse` shape (0047) — replaces the
    legacy bus-level `ValidationResponse` / `CorrelationResult` /
    `ScatterPoint` types.
"""
from __future__ import annotations


def _props(schema: dict, name: str) -> dict:
    return schema['components']['schemas'][name]['properties']


def test_openapi_carries_renamed_fields(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    spec = r.json()

    bus = _props(spec, 'BusState')
    assert 'modeled_congestion' in bus
    assert 'binding_proximity' in bus

    meta = _props(spec, 'SnapshotMeta')
    for f in (
        'modeled_congestion_total',
        'modeled_congestion_abs_total',
        'modeled_congestion_top10_share',
        'binding_proximity_max',
        'binding_proximity_p95',
    ):
        assert f in meta, f

    schemas = spec['components']['schemas']
    for legacy in ('CorrelationResult', 'ScatterPoint', 'ValidationResponse'):
        assert legacy not in schemas, f'{legacy} should have been removed'

    scorecard = _props(spec, 'ScorecardResponse')
    for f in ('run_id', 'params', 'headline', 'zones', 'series', 'warnings'):
        assert f in scorecard, f

    zone = _props(spec, 'ScorecardZone')
    for f in ('cluster_id', 'n_buses', 'n_sps', 'corr', 'sign_agreement',
              'model_side_std', 'ercot_side_std', 'outlier_buses', 'outlier_sps'):
        assert f in zone, f

    headline = _props(spec, 'ScorecardHeadline')
    for f in ('zone_rank_spearman_per_hour', 'mean_corr', 'mean_sign_agreement', 'n_hours', 'n_zones'):
        assert f in headline, f

    series = _props(spec, 'ScorecardSeries')
    for f in ('hours', 'cluster_ids', 'model_Z', 'ercot_Z'):
        assert f in series, f
