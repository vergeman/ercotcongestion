"""Unit tests for the bounded causal /matrix/frame contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import matrix as matrix_module
from compute.sf.project import build_sf_mu_artifact


T0 = datetime(2026, 7, 1, 5, tzinfo=timezone.utc)  # midnight Central
T1 = datetime(2026, 7, 1, 6, tzinfo=timezone.utc)


def _blob() -> bytes:
    sf = pd.DataFrame(
        {'SP_A': [1.0, 0.5, 0.1], 'SP_B': [-0.2, 0.3, 0.7], 'SP_C': [0.1, 0.4, 0.2]},
        index=['AAA|BASE', 'BBB|LINE', 'CCC|OUTAGE'],
    )
    mu = pd.DataFrame(
        {'AAA|BASE': [2.0, 1.0], 'BBB|LINE': [3.0, 0.0], 'CCC|OUTAGE': [0.0, 2.0]},
        index=pd.to_datetime([T0, T1], utc=True),
    )
    return build_sf_mu_artifact(sf, mu)


def _full_utc_day_blob(day: datetime) -> bytes:
    sf = pd.DataFrame({'SP_A': [1.0]}, index=['AAA|BASE'])
    hours = pd.date_range(day, periods=24, freq='h', tz='UTC')
    mu = pd.DataFrame({'AAA|BASE': range(24)}, index=hours)
    return build_sf_mu_artifact(sf, mu)


def _anchor_blob() -> bytes:
    # Two default anchors out of order + an extra hub and a non-anchor node, so
    # 'default_anchors' must both filter and re-order to the canonical list.
    sf = pd.DataFrame(
        {'HB_NORTH': [0.4], 'HB_HOUSTON': [0.6], 'HB_BUSAVG': [0.9], 'SP_X': [0.2]},
        index=['AAA|BASE'],
    )
    mu = pd.DataFrame({'AAA|BASE': [2.0]}, index=pd.to_datetime([T0], utc=True))
    return build_sf_mu_artifact(sf, mu)


def _anchor_contribution_blob() -> bytes:
    # A high-μ constraint with no anchor reach (only a non-anchor node), and two
    # constraints that do reach the anchors, so anchor_contribution both filters
    # the blank-anchor row out and ranks by μ × reach into the anchors.
    sf = pd.DataFrame(
        {
            'HB_HOUSTON': [0.0, 0.5, 0.2],
            'HB_NORTH': [0.0, 0.3, 0.1],
            'SP_X': [0.9, 0.1, 0.0],
        },
        index=['HIGHMU_NOREACH|BASE', 'MIDMU_REACH|BASE', 'LOWMU_REACH|BASE'],
    )
    mu = pd.DataFrame(
        {'HIGHMU_NOREACH|BASE': [100.0], 'MIDMU_REACH|BASE': [10.0], 'LOWMU_REACH|BASE': [5.0]},
        index=pd.to_datetime([T0], utc=True),
    )
    return build_sf_mu_artifact(sf, mu)


def _hub_zone_blob() -> bytes:
    sf = pd.DataFrame(
        {'SP_A': [0.9], 'HB_WEST': [0.734], 'LZ_COAST': [0.5]},
        index=['AAA|BASE'],
    )
    mu = pd.DataFrame({'AAA|BASE': [2.0]}, index=pd.to_datetime([T0], utc=True))
    return build_sf_mu_artifact(sf, mu)


def _queue_frame(fake_pool, dam_rows: list[dict] | None = None, type_rows: list[dict] | None = None):
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])          # 0123: coalesce min(horizon) probe
    fake_pool.cursor.queue([{'sf_npz': _blob()}])
    fake_pool.cursor.queue(dam_rows or [])
    fake_pool.cursor.queue(type_rows or [])


def test_frame_is_causal_dense_and_dam_partial(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('hub', 'north_hub'), 'SP_B': ('load_zone', 'west'), 'SP_C': ('resource', None),
    })
    _queue_frame(fake_pool, [
        {'constraint_name': ' BBB ', 'contingency_name': ' LINE ', 'shadow_price': 9.0},
    ])

    response = client.get('/matrix/frame', params={
        'interval_ts': '2026-07-01T05:00:00Z', 'row_limit': 2, 'column_limit': 2,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['available'] is True
    assert body['delivery_date'] == '2026-07-01'
    assert body['dam_status'] == 'partial'
    # Daily ordering is independent of the selected hour: AAA (3*1.3) beats
    # BBB (3*1.2), and CCC is outside the requested bounded row universe.
    assert [r['constraint_key'] for r in body['rows']] == ['AAA|BASE', 'BBB|LINE']
    assert [r['forecast_mu'] for r in body['rows']] == [2.0, 3.0]
    assert [r['ercot_dam_mu'] for r in body['rows']] == [None, 9.0]
    assert [c['settlement_point'] for c in body['columns']] == ['SP_A', 'SP_C']
    assert body['columns'][0]['settlement_point_type'] == 'hub'
    # Row-major: AAA×(A,C), BBB×(A,C), exactly aligned to the labels above.
    assert body['sf']['row_count'] == 2 and body['sf']['column_count'] == 2
    assert body['sf']['values'] == pytest.approx([1.0, 0.1, 0.5, 0.4])
    assert body['rows_truncated'] is True
    assert body['columns_truncated'] is True
    assert body['total_constraint_count'] == 3
    assert body['total_settlement_point_count'] == 3
    assert body['sf_day_max_abs'] == pytest.approx(1.0)
    assert body['contribution_day_max_abs'] == pytest.approx(2.0)
    assert body['fit_window_start'] is None and body['fit_window_end'] is None


def test_frame_rounds_matrix_display_values_to_three_decimals(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('hub', None), 'SP_B': ('resource', None),
    })
    sf = pd.DataFrame(
        {'SP_A': [0.12349], 'SP_B': [-0.98765]}, index=['AAA|BASE']
    )
    mu = pd.DataFrame({'AAA|BASE': [2.3456]}, index=pd.to_datetime([T0], utc=True))
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])          # 0123: coalesce min(horizon) probe
    fake_pool.cursor.queue([{'sf_npz': build_sf_mu_artifact(sf, mu)}])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])

    response = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'row_limit': 1, 'column_limit': 2,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['rows'][0]['forecast_mu'] == 2.346
    assert body['rows'][0]['max_abs_sf'] == 0.988
    assert [column['max_abs_sf'] for column in body['columns']] == [0.988, 0.123]
    assert body['sf']['values'] == [-0.988, 0.123]


def test_frame_order_does_not_change_by_hour(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {})
    _queue_frame(fake_pool)
    first = client.get('/matrix/frame', params={'interval_ts': T0.isoformat(), 'row_limit': 2, 'column_limit': 2})
    # Cache reuse skips the blob fetch, but pointer, the min(horizon) probe, and the
    # exact-hour DAM still query (0123: the probe runs before the cache is consulted).
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])          # coalesce probe (cache hit follows)
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    second = client.get('/matrix/frame', params={'interval_ts': T1.isoformat(), 'row_limit': 2, 'column_limit': 2})
    assert first.status_code == second.status_code == 200
    assert [r['constraint_key'] for r in first.json()['rows']] == [r['constraint_key'] for r in second.json()['rows']]
    assert [c['settlement_point'] for c in first.json()['columns']] == [c['settlement_point'] for c in second.json()['columns']]


def test_frame_reports_missing_artifact_without_fallback(client, fake_pool):
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([])
    response = client.get('/matrix/frame', params={'interval_ts': T0.isoformat()})
    assert response.status_code == 200
    assert response.json()['available'] is False
    assert response.json()['unavailable_reason'] == 'artifact_missing'
    assert response.json()['sf']['values'] == []


def test_frame_reports_interval_absent_from_artifact(client, fake_pool):
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])          # 0123: coalesce min(horizon) probe
    fake_pool.cursor.queue([{'sf_npz': _blob()}])
    response = client.get('/matrix/frame', params={'interval_ts': '2026-07-01T07:00:00Z'})
    assert response.status_code == 200
    assert response.json()['available'] is False
    assert response.json()['unavailable_reason'] == 'interval_not_in_artifact'


def test_delivery_date_uses_central_time_boundary():
    assert matrix_module._delivery_date(datetime(2026, 7, 1, 4, 59, tzinfo=timezone.utc)).isoformat() == '2026-06-30'
    assert matrix_module._delivery_date(T0).isoformat() == '2026-07-01'


def test_frame_resolves_all_utc_day_hours_from_one_utc_artifact(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {})
    utc_day = datetime(2026, 7, 1, tzinfo=timezone.utc)
    artifact = _full_utc_day_blob(utc_day)
    for hour in range(24):
        fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
        fake_pool.cursor.queue([{'h': 1}])      # 0123: coalesce probe every hour
        if hour == 0:
            fake_pool.cursor.queue([{'sf_npz': artifact}])
        fake_pool.cursor.queue([])
        fake_pool.cursor.queue([])

    frames = [
        client.get('/matrix/frame', params={'interval_ts': (utc_day + timedelta(hours=hour)).isoformat()})
        for hour in range(24)
    ]

    assert all(frame.status_code == 200 and frame.json()['available'] for frame in frames)
    # 00:00–04:00 UTC retain their Central delivery label, while every request
    # still resolves the same July 1 UTC artifact.
    assert frames[0].json()['delivery_date'] == '2026-06-30'
    # queries[1] is the coalesce min(horizon) probe (0123); it targets the artifact's
    # UTC day, the same (run_id, date) the blob fetch then uses.
    probe_query = fake_pool.cursor.queries[1]
    assert probe_query[1] == ('fc-v1', utc_day.date())


def test_frame_enforces_conservative_bounds(client):
    response = client.get('/matrix/frame', params={'interval_ts': T0.isoformat(), 'row_limit': 101})
    assert response.status_code == 422
    response = client.get('/matrix/frame', params={'interval_ts': T0.isoformat(), 'column_limit': 101})
    assert response.status_code == 422


def test_frame_anchor_columns_include_artifact_hubs_and_load_zones(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('resource', None),
        'HB_WEST': ('hub', 'west_hub'),
        'LZ_COAST': ('load_zone', 'coast'),
    })
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])          # 0123: coalesce min(horizon) probe
    fake_pool.cursor.queue([{'sf_npz': _hub_zone_blob()}])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])

    response = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'column_set': 'anchors',
    })

    assert response.status_code == 200, response.text
    columns = response.json()['columns']
    assert [column['settlement_point'] for column in columns] == ['HB_WEST', 'LZ_COAST']
    assert [(column['settlement_point_type'], column['load_zone']) for column in columns] == [
        ('hub', 'west_hub'), ('load_zone', 'coast'),
    ]


def test_frame_discovery_pins_search_types_and_column_presets(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('hub', 'north_hub'), 'SP_B': ('resource', None), 'SP_C': ('load_zone', 'west'),
    })
    _queue_frame(fake_pool, type_rows=[
        {'constraint_key': 'AAA|BASE', 'ctype': 'gtc'},
        {'constraint_key': 'BBB|LINE', 'ctype': 'transmission'},
        {'constraint_key': 'CCC|OUTAGE', 'ctype': 'radial'},
    ])
    response = client.get('/matrix/frame', params=[
        ('interval_ts', T0.isoformat()), ('row_preset', 'pinned'),
        ('pinned_constraint', 'CCC|OUTAGE'), ('constraint_search', 'bbb'),
        ('constraint_type', 'gtc'), ('column_set', 'anchors'),
        ('pinned_settlement_point', 'SP_B'), ('settlement_point_search', 'sp_a'),
    ])
    assert response.status_code == 200, response.text
    body = response.json()
    # Pins and search results append in a deterministic order; a type filter
    # never silently drops a pin the user explicitly curated.
    assert [row['constraint_key'] for row in body['rows']] == ['CCC|OUTAGE', 'BBB|LINE']
    assert [row['constraint_type'] for row in body['rows']] == ['radial', 'transmission']
    assert [column['settlement_point'] for column in body['columns']] == ['SP_A', 'SP_B']


def test_frame_rejects_unbounded_discovery_values(client):
    response = client.get('/matrix/frame', params=[('interval_ts', T0.isoformat())] + [('pinned_constraint', f'C{i}') for i in range(21)])
    assert response.status_code == 422
    response = client.get('/matrix/frame', params={'interval_ts': T0.isoformat(), 'constraint_search': 'x' * 65})
    assert response.status_code == 422


def test_frame_default_orientation_is_constraints(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {})
    _queue_frame(fake_pool)
    response = client.get('/matrix/frame', params={'interval_ts': T0.isoformat(), 'row_limit': 2, 'column_limit': 2})
    assert response.status_code == 200, response.text
    assert response.json()['orientation'] == 'constraints'


def test_frame_orientation_nodes_transposes_selection(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('resource', None), 'SP_B': ('load_zone', 'west'), 'SP_C': ('resource', None),
    })
    _queue_frame(fake_pool)
    response = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'orientation': 'nodes', 'row_limit': 2, 'column_limit': 2,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['orientation'] == 'nodes'
    # The wire stays constraint-major: rows are constraints, columns nodes. With
    # no pins the constraint column seeds to the max-forecast-μ constraint at the
    # cursor (BBB, |μ|=3 beats AAA's 2), and node rows rank by |SF| against it:
    # SP_A(0.5), SP_C(0.4) lead SP_B(0.3), bounded to row_limit=2.
    assert [r['constraint_key'] for r in body['rows']] == ['BBB|LINE']
    assert [c['settlement_point'] for c in body['columns']] == ['SP_A', 'SP_C']
    assert body['sf']['values'] == pytest.approx([0.5, 0.4])


def test_frame_orientation_nodes_seed_prefers_dam_and_yields_to_pin(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {})
    # DAM μ for AAA (|10|) outranks BBB's forecast |μ|=3, so the unpinned seed is AAA.
    _queue_frame(fake_pool, dam_rows=[
        {'constraint_name': 'AAA', 'contingency_name': 'BASE', 'shadow_price': 10.0},
    ])
    seeded = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'orientation': 'nodes', 'row_limit': 3, 'column_limit': 2,
    })
    assert seeded.status_code == 200, seeded.text
    assert [r['constraint_key'] for r in seeded.json()['rows']] == ['AAA|BASE']

    # Pinning a constraint replaces the seed with the pinned column entirely.
    # The artifact is now cached, so the blob fetch is skipped (0123: the probe
    # still runs before the cache is consulted); queue only the live queries.
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    pinned = client.get('/matrix/frame', params=[
        ('interval_ts', T0.isoformat()), ('orientation', 'nodes'),
        ('row_limit', '3'), ('column_limit', '2'), ('pinned_constraint', 'CCC|OUTAGE'),
    ])
    assert pinned.status_code == 200, pinned.text
    # CCC drives SP_B(0.7) hardest, then SP_C(0.2), then SP_A(0.1); bounded to 3.
    assert [r['constraint_key'] for r in pinned.json()['rows']] == ['CCC|OUTAGE']
    assert [c['settlement_point'] for c in pinned.json()['columns']] == ['SP_B', 'SP_C', 'SP_A']


def test_frame_orientation_nodes_search_forces_node_row_past_cap(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {})
    _queue_frame(fake_pool)
    response = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'orientation': 'nodes',
        'row_limit': 2, 'column_limit': 2, 'settlement_point_search': 'sp_b',
    })
    assert response.status_code == 200, response.text
    # Against the BBB seed SP_B ranks last (0.3) and is outside the top-2 rows,
    # but the node search force-includes it just as the constraint axis does.
    assert [c['settlement_point'] for c in response.json()['columns']] == ['SP_B']


def test_frame_constraints_orientation_seeds_a_hub_column(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('resource', None), 'HB_WEST': ('hub', 'west_hub'), 'LZ_COAST': ('load_zone', 'coast'),
    })
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])
    fake_pool.cursor.queue([{'sf_npz': _hub_zone_blob()}])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    # column_set='pinned' with no node pins seeds the single best-reaching hub.
    response = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'column_set': 'pinned', 'column_limit': 5,
    })
    assert response.status_code == 200, response.text
    columns = response.json()['columns']
    assert [c['settlement_point'] for c in columns] == ['HB_WEST']
    assert columns[0]['settlement_point_type'] == 'hub'


def test_frame_default_anchors_columns_are_curated_and_ordered(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'HB_NORTH': ('hub', None), 'HB_HOUSTON': ('hub', None),
        'HB_BUSAVG': ('hub', None), 'SP_X': ('resource', None),
    })
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])
    fake_pool.cursor.queue([{'sf_npz': _anchor_blob()}])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    response = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'column_set': 'default_anchors', 'column_limit': 30,
    })
    assert response.status_code == 200, response.text
    # Canonical order (HB_HOUSTON before HB_NORTH), and the *_AVG hub / non-anchor
    # node are excluded even though they exist in the artifact.
    assert [c['settlement_point'] for c in response.json()['columns']] == ['HB_HOUSTON', 'HB_NORTH']


def test_frame_anchor_contribution_ranks_by_reach_and_drops_blank_rows(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'HB_HOUSTON': ('hub', None), 'HB_NORTH': ('hub', None), 'SP_X': ('resource', None),
    })
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])
    fake_pool.cursor.queue([{'sf_npz': _anchor_contribution_blob()}])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    response = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'row_order': 'anchor_contribution',
        'column_set': 'default_anchors', 'row_limit': 5, 'column_limit': 30,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    # HIGHMU_NOREACH (|μ|=100) is dropped despite the largest μ — its peak anchor
    # |SF| is 0. The rest rank by μ × Σ|SF| over anchors: MID (10×0.8=8) > LOW
    # (5×0.3=1.5).
    assert [r['constraint_key'] for r in body['rows']] == ['MIDMU_REACH|BASE', 'LOWMU_REACH|BASE']
    assert [c['settlement_point'] for c in body['columns']] == ['HB_HOUSTON', 'HB_NORTH']


def test_frame_row_order_cursor_mu_ranks_by_dam_then_forecast(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {})
    # Forecast |μ| at T0: BBB(3) > AAA(2) > CCC(0). cursor_mu therefore selects
    # [BBB, AAA] — the reverse of the contribution default's [AAA, BBB].
    _queue_frame(fake_pool)
    forecast = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'row_order': 'cursor_mu', 'row_limit': 2, 'column_limit': 1,
    })
    assert forecast.status_code == 200, forecast.text
    body = forecast.json()
    assert [r['constraint_key'] for r in body['rows']] == ['BBB|LINE', 'AAA|BASE']
    # daily_rank stays the contribution rank (AAA=1) regardless of the selection order.
    assert {r['constraint_key']: r['daily_rank'] for r in body['rows']}['AAA|BASE'] == 1

    # Published DAM μ for AAA (|9|) outranks BBB's forecast |μ|=3, floating AAA up.
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])
    fake_pool.cursor.queue([{'constraint_name': 'AAA', 'contingency_name': 'BASE', 'shadow_price': 9.0}])
    fake_pool.cursor.queue([])
    dam = client.get('/matrix/frame', params={
        'interval_ts': T0.isoformat(), 'row_order': 'cursor_mu', 'row_limit': 2, 'column_limit': 1,
    })
    assert dam.status_code == 200, dam.text
    assert [r['constraint_key'] for r in dam.json()['rows']] == ['AAA|BASE', 'BBB|LINE']


def test_frame_peek_force_includes_preview_beyond_the_working_set(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('hub', None), 'SP_B': ('resource', None), 'SP_C': ('resource', None),
    })
    _queue_frame(fake_pool)
    # A pure working-set request: pinned rows/cols only, plus one previewed
    # (un-pinned) constraint row and settlement-point column via peek.
    response = client.get('/matrix/frame', params=[
        ('interval_ts', T0.isoformat()), ('row_preset', 'pinned'), ('column_set', 'pinned'),
        ('pinned_constraint', 'AAA|BASE'), ('pinned_settlement_point', 'SP_A'),
        ('peek_constraint', 'CCC|OUTAGE'), ('peek_settlement_point', 'SP_C'),
    ])
    assert response.status_code == 200, response.text
    body = response.json()
    # The working set (AAA, SP_A) plus the peeked preview (CCC, SP_C) — and only those.
    assert set(r['constraint_key'] for r in body['rows']) == {'AAA|BASE', 'CCC|OUTAGE'}
    assert set(c['settlement_point'] for c in body['columns']) == {'SP_A', 'SP_C'}


def test_frame_constraints_orientation_hub_seed_yields_to_node_pin(client, fake_pool, monkeypatch):
    monkeypatch.setattr(matrix_module, '_SP_METADATA', {
        'SP_A': ('resource', None), 'HB_WEST': ('hub', 'west_hub'), 'LZ_COAST': ('load_zone', 'coast'),
    })
    fake_pool.cursor.queue([{'run_id': 'fc-v1'}])
    fake_pool.cursor.queue([{'h': 1}])
    fake_pool.cursor.queue([{'sf_npz': _hub_zone_blob()}])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    response = client.get('/matrix/frame', params=[
        ('interval_ts', T0.isoformat()), ('column_set', 'pinned'), ('column_limit', '5'),
        ('pinned_settlement_point', 'LZ_COAST'),
    ])
    assert response.status_code == 200, response.text
    # A pinned node suppresses the hub seed entirely.
    assert [c['settlement_point'] for c in response.json()['columns']] == ['LZ_COAST']
