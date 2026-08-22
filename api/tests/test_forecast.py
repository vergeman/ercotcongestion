"""Unit tests for GET /forecast_range — per-day horizon coalesce + provenance (0123).

The FakeCursor (conftest) replays queued rows FIFO without inspecting SQL, so each
test queues exactly the rows the endpoint's queries return in order. The SQL-side
per-(ts, sp) coalesce (DISTINCT ON horizon ASC) is exercised against the real dev DB
separately; here the rows arrive already coalesced, so these pin the Python-side
provenance map, the response shape, and the explicit-horizon status-code contract.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

import forecast as forecast_module


def _frow(ts, sp, dd, horizon, p50=1.0):
    return {"ts": ts, "settlement_point": sp,
            "p10": p50 - 0.5, "p50": p50, "p90": p50 + 0.5,
            "delivery_date": dd, "horizon": horizon}


_WINDOW = "start=2026-08-01T00:00:00Z&end=2026-08-02T23:00:00Z"


@pytest.fixture(autouse=True)
def published_run(client):
    client.app.dependency_overrides[forecast_module._server_selected_run] = lambda: "m"
    yield
    client.app.dependency_overrides.pop(forecast_module._server_selected_run, None)


def test_coalesced_range_reports_per_day_horizon_provenance(client, fake_pool):
    """A window spanning a final day and a preview-only day returns one gapless
    series; `horizons` says which horizon each day came from."""
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
    d0, d1 = date(2026, 8, 1), date(2026, 8, 2)
    fake_pool.cursor.queue([_frow(t0, "SP", d0, 1),      # final
                            _frow(t1, "SP", d1, 2)])     # preview-only
    fake_pool.cursor.queue([{"interval_ts": t0, "system_lambda": 10.0},
                            {"interval_ts": t1, "system_lambda": 11.0}])

    r = client.get(f"/forecast_range?{_WINDOW}")
    assert r.status_code == 200
    body = r.json()
    assert body["horizons"] == {"2026-08-01": 1, "2026-08-02": 2}
    assert body["count"] == 2                            # two hours, no gap
    assert body["run_id"] == "m"


def test_explicit_horizon_serves_only_that_track(client, fake_pool):
    """`?horizon=2` reads the preserved preview; provenance reflects horizon 2."""
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    d0 = date(2026, 8, 1)
    fake_pool.cursor.queue([_frow(t0, "SP", d0, 2)])
    fake_pool.cursor.queue([{"interval_ts": t0, "system_lambda": 10.0}])

    r = client.get(f"/forecast_range?{_WINDOW}&horizon=2")
    assert r.status_code == 200
    assert r.json()["horizons"] == {"2026-08-01": 2}


def test_explicit_horizon_404s_when_that_track_is_absent(client, fake_pool):
    """`?horizon=1` on a preview-only day has no rows and 404s — no fallback to the
    preview (the explicit read is the 'what changed' view, not a coalesce)."""
    fake_pool.cursor.queue([])       # main query: no horizon-1 rows
    fake_pool.cursor.queue([])       # lambda
    r = client.get(f"/forecast_range?{_WINDOW}&horizon=1")
    assert r.status_code == 404


def test_coalesced_no_rows_keeps_the_503_softfail(client, fake_pool):
    """Without an explicit horizon, an empty window keeps the realized-range 503
    soft-fail contract (the client renders the realized pane alone)."""
    fake_pool.cursor.queue([])       # main query: nothing
    fake_pool.cursor.queue([])       # lambda
    r = client.get(f"/forecast_range?{_WINDOW}")
    assert r.status_code == 503


def test_horizon_out_of_range_is_rejected(client):
    """Only 1 and 2 are valid horizons; anything else is a 422 before any query."""
    assert client.get(f"/forecast_range?{_WINDOW}&horizon=3").status_code == 422


def test_unsettled_hour_falls_back_to_persisted_lambda(client, fake_pool):
    """An hour with no dam_system_lambda row (unsettled) is filled from the most
    recent settled day's λ at the same Central hour; a settled hour is untouched
    and each entry's `lambda_source` says which curve served it."""
    t0 = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)   # settled
    t1 = datetime(2026, 8, 2, 15, 0, tzinfo=timezone.utc)   # unsettled, same CT hour
    d0, d1 = date(2026, 8, 1), date(2026, 8, 2)
    fake_pool.cursor.queue([_frow(t0, "SP", d0, 1), _frow(t1, "SP", d1, 1)])
    fake_pool.cursor.queue([{"interval_ts": t0, "system_lambda": 10.0}])  # t1 absent
    fake_pool.cursor.queue([{"interval_ts": t0, "system_lambda": 10.0}])  # persisted ref day

    r = client.get(f"/forecast_range?{_WINDOW}")
    assert r.status_code == 200
    entries = sorted(r.json()["entries"], key=lambda e: e["interval_ts"])
    settled, unsettled = entries
    assert settled["system_lambda"] == 10.0
    assert settled["lambda_source"] == "settled"
    assert unsettled["system_lambda"] == 10.0
    assert unsettled["lambda_source"] == "persisted"


def test_fully_settled_window_skips_the_persistence_query(client, fake_pool):
    """Every hour already has a settled λ, so the third (persisted-reference)
    query never fires — a pure history scrub queues only two responses."""
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    d0 = date(2026, 8, 1)
    fake_pool.cursor.queue([_frow(t0, "SP", d0, 1)])
    fake_pool.cursor.queue([{"interval_ts": t0, "system_lambda": 10.0}])

    r = client.get(f"/forecast_range?{_WINDOW}")
    assert r.status_code == 200
    entry = r.json()["entries"][0]
    assert entry["lambda_source"] == "settled"
    assert fake_pool.cursor.responses == []  # nothing left unread
