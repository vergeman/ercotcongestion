"""Schema regression guard.

After the 0090 teardown the OpenAPI surface carries only the kept endpoints'
schemas. Locks in that the synthetic-grid / scorecard / IBP models are gone and
the realized-ERCOT + meta models remain.
"""
from __future__ import annotations


def test_openapi_omits_deleted_schemas(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    schemas = r.json()['components']['schemas']

    deleted = (
        # synthetic PyPSA state
        'BusState', 'BindingLine', 'Contingency', 'ZoneOutage', 'SnapshotMeta',
        'StateResponse', 'StateRangeEntry', 'StateRangeResponse',
        # clustering scorecard
        'ScorecardZone', 'ScorecardHeadline', 'ScorecardSeries', 'ScorecardParams',
        'MappingCorrelationSummary', 'ScorecardResponse',
        # legacy validation types
        'CorrelationResult', 'ScatterPoint', 'ValidationResponse',
        # unused topology model + IBP set
        'TopologyResponse',
        'IbpErcotPoint', 'IbpErcotResponse', 'IbpErcotRangeEntry', 'IbpErcotRangeResponse',
    )
    for name in deleted:
        assert name not in schemas, f'{name} should have been removed'


def test_openapi_keeps_realized_and_meta_schemas(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    schemas = r.json()['components']['schemas']

    for name in ('ErcotStateRangeResponse', 'ErcotSppRangeResponse', 'MetaResponse'):
        assert name in schemas, f'{name} should be present'


def test_openapi_includes_map_schemas(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    schemas = r.json()['components']['schemas']

    for name in ('MapMeta', 'ConstraintGeo', 'SpExposure', 'ExposuresResponse',
                 'ConstraintReach', 'ReachSp'):
        assert name in schemas, f'{name} should be present'
