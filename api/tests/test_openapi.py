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
        # retired API-only resources
        'AnalysisEsspGroupsAvailableResponse', 'AnalysisEsspGroupsUnavailableResponse',
        'BriefDayResponse', 'EsspGroup',
    )
    for name in deleted:
        assert name not in schemas, f'{name} should have been removed'


def test_openapi_keeps_realized_schemas(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    schemas = r.json()['components']['schemas']

    for name in ('ErcotRangeResponse',):
        assert name in schemas, f'{name} should be present'
    for name in ('ErcotStateRangeResponse', 'ErcotSppRangeResponse'):
        assert name not in schemas, f'{name} should be removed'


def test_openapi_includes_map_schemas(client):
    r = client.get('/openapi.json')
    assert r.status_code == 200
    schemas = r.json()['components']['schemas']

    for name in ('SpExposure', 'ExposuresResponse',
                 'ConstraintReach', 'ReachSp'):
        assert name in schemas, f'{name} should be present'


def test_openapi_documents_contract_migrations_and_bootstrap_availability(client):
    schema = client.get('/openapi.json').json()
    paths = schema['paths']
    schemas = schema['components']['schemas']

    assert '/ercot_state_range' not in paths
    assert '/ercot_spp_range' not in paths

    retired_routes = {
        '/map/meta', '/map/overview', '/analysis/hero', '/analysis/brief',
        '/analysis/grade', '/analysis/essp',
    }
    assert retired_routes.isdisjoint(paths)

    bootstrap_status = schemas['BootstrapSectionStatus']['properties']
    assert {'available', 'unavailable_reason', 'run_id', 'delivery_date', 'horizon'} <= bootstrap_status.keys()
    for name in ('MapSummaryResponse', 'ScoreboardSummaryResponse'):
        assert 'availability' in schemas[name]['properties']


def test_openapi_hides_backend_run_selection_from_public_read_routes(client):
    paths = client.get('/openapi.json').json()['paths']
    public_routes = (
        '/forecast_range', '/map/constraints/ranked', '/analysis/hero/latest',
        '/analysis/brief/hero',
        '/analysis/brief/details', '/analysis/node',
        '/analysis/settlement-points', '/analysis/constraints',
        '/analysis/standouts',
    )
    for route in public_routes:
        names = {parameter['name'] for parameter in paths[route]['get'].get('parameters', [])}
        assert 'run_id' not in names, route
        assert 'run' not in names, route


def test_openapi_keeps_scoreboard_as_one_summary_resource(client):
    paths = client.get('/openapi.json').json()['paths']
    assert '/scoreboard/summary' in paths
    assert {'/scoreboard/headline', '/scoreboard/weekly', '/scoreboard/daily'}.isdisjoint(paths)
