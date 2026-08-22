"""Schema regression guard.

After the 0090 teardown the OpenAPI surface carries only the kept endpoints'
schemas. Locks in that the synthetic-grid / scorecard / IBP models are gone and
the realized-ERCOT models remain.
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
        # legacy zonal-map serving snapshot (removed in 0094-0001)
        'MetaResponse',
    )
    for name in deleted:
        assert name not in schemas, f'{name} should have been removed'


def test_openapi_keeps_realized_schemas(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    schemas = r.json()['components']['schemas']

    for name in ('ErcotRangeResponse', 'ErcotStateRangeResponse', 'ErcotSppRangeResponse'):
        assert name in schemas, f'{name} should be present'


def test_openapi_includes_map_schemas(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    schemas = r.json()['components']['schemas']

    for name in ('MapMeta', 'SpExposure', 'ExposuresResponse',
                 'ConstraintReach', 'ReachSp'):
        assert name in schemas, f'{name} should be present'


def test_openapi_documents_contract_migrations_and_bootstrap_availability(client):
    schema = client.get('/openapi.json').json()
    paths = schema['paths']
    schemas = schema['components']['schemas']

    assert paths['/ercot_state_range']['get']['deprecated'] is True
    assert paths['/ercot_spp_range']['get']['deprecated'] is True

    brief_parameters = {
        parameter['name']: parameter
        for parameter in paths['/analysis/brief']['get']['parameters']
    }
    assert {'delivery_date', 'run_id', 'day', 'run'} <= brief_parameters.keys()
    assert brief_parameters['day']['deprecated'] is True
    assert brief_parameters['run']['deprecated'] is True

    bootstrap_status = schemas['BootstrapSectionStatus']['properties']
    assert {'available', 'unavailable_reason', 'run_id', 'delivery_date', 'horizon'} <= bootstrap_status.keys()
    for name in ('MapSummaryResponse', 'ScoreboardSummaryResponse'):
        assert 'availability' in schemas[name]['properties']
