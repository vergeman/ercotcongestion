"""Schema regression guard: OpenAPI spec reflects the post-fragility renames.

Fails loudly if `BusState`, `SnapshotMeta`, `ScatterPoint`, or `ValidationResponse`
regain a `fragility*` field or lose one of the new metric fields.
"""
from __future__ import annotations


def _props(schema: dict, name: str) -> dict:
    return schema['components']['schemas'][name]['properties']


def test_openapi_carries_renamed_fields_and_no_fragility(client):
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

    scatter = _props(spec, 'ScatterPoint')
    for f in ('modeled_congestion', 'basis', 'abs_basis'):
        assert f in scatter, f

    validation = _props(spec, 'ValidationResponse')
    for f in ('sign_agreement_overall', 'sign_agreement_congested'):
        assert f in validation, f

    # No lingering fragility fields anywhere in the schema tree.
    flat = str(spec['components']['schemas'])
    assert 'fragility' not in flat
