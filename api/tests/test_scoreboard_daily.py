"""Tests for GET /scoreboard/daily — the live per-delivery-day board (0003).

The fake cursor is FIFO: when ``run_id`` is omitted the run-resolution query fires
first (one row), then the horizon-resolution query, then the per-day SELECT; with
an explicit ``run_id`` the horizon query leads. Rows are queued as dicts because
the route uses ``dict_row``.
"""
from __future__ import annotations

from datetime import date


def _row(source, **kw):
    base = {"delivery_date": date(2026, 7, 18), "source": source, "horizon": 1}
    base.update(kw)
    return base


def _horizons(*values):
    """The DISTINCT-horizon result set the route reads before the per-day SELECT."""
    return [{"horizon": h} for h in values]


def test_daily_serves_all_sources_with_bands_on_model_only(client, fake_pool):
    # Explicit run_id → no run-resolve query; horizons first, then the per-day rows.
    fake_pool.cursor.queue(_horizons(1, 2))
    fake_pool.cursor.queue([
        _row("model", topdecile_hit=0.61, coverage80=0.72, band_width=12.0,
             pinball=3.1, sf_coverage=0.9, model_coverage=None, n_hours=24,
             n_nodes=900),
        _row("persistence", topdecile_hit=0.56, sf_coverage=0.9),
        _row("climatology", topdecile_hit=0.30, sf_coverage=0.9),
        _row("oracle", topdecile_hit=0.79, sf_coverage=0.9),
        _row("null", topdecile_hit=None, rank_spearman=None, sf_coverage=0.9),
    ])

    r = client.get("/scoreboard/daily", params={"run_id": "mu-all-v1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "mu-all-v1"
    assert body["primary_source"] == "model"

    by_src = {p["source"]: p for p in body["points"]}
    # Integrity rule (§6): baselines + oracle + tripwire ride with the model.
    assert {"model", "persistence", "climatology", "oracle", "null"} <= set(by_src)

    # Bands live on the model source only.
    assert by_src["model"]["coverage80"] == 0.72
    assert by_src["persistence"]["coverage80"] is None

    # The null tripwire's declined screening rides through as null, never a number.
    assert by_src["null"]["topdecile_hit"] is None
    assert by_src["null"]["rank_spearman"] is None


def test_daily_resolves_latest_run_when_run_id_omitted(client, fake_pool):
    fake_pool.cursor.queue([{"run_id": "mu-all-v2"}])            # run resolution
    fake_pool.cursor.queue(_horizons(1))                         # horizon resolution
    fake_pool.cursor.queue([_row("model", topdecile_hit=0.6)])  # per-day query
    r = client.get("/scoreboard/daily")
    assert r.status_code == 200, r.text
    assert r.json()["run_id"] == "mu-all-v2"


def test_daily_since_filters_the_query(client, fake_pool):
    fake_pool.cursor.queue(_horizons(1))
    fake_pool.cursor.queue([_row("model", topdecile_hit=0.6)])
    r = client.get("/scoreboard/daily",
                   params={"run_id": "r", "since": "2026-07-01"})
    assert r.status_code == 200, r.text
    assert r.json()["since"] == "2026-07-01"
    sql, params = fake_pool.cursor.queries[-1]
    assert "delivery_date >= %s" in sql
    assert date(2026, 7, 1) in params


def test_daily_503_when_no_grades_loaded(client, fake_pool):
    fake_pool.cursor.queue([])   # resolution finds nothing
    r = client.get("/scoreboard/daily")
    assert r.status_code == 503


def test_daily_503_when_run_has_no_rows(client, fake_pool):
    # Explicit run_id skips run resolution; both remaining queries come back empty.
    fake_pool.cursor.queue([])
    r = client.get("/scoreboard/daily", params={"run_id": "ghost"})
    assert r.status_code == 503
    assert "ghost" in r.json()["detail"]


def test_openapi_exposes_daily_schemas(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("ScoreboardDaily", "DailyPoint"):
        assert name in schemas


def test_daily_defaults_to_the_final_horizon_and_filters_on_it(client, fake_pool):
    """Two graded tracks must never be interleaved: `scoreboard_daily` holds one
    row per (delivery_date, source, horizon), so an unfiltered query returns a
    final grade and a preview grade for the same day and a client keying by
    source alone keeps whichever arrived last."""
    fake_pool.cursor.queue(_horizons(1, 2))
    fake_pool.cursor.queue([_row("model", topdecile_hit=0.6)])

    r = client.get("/scoreboard/daily", params={"run_id": "r"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["horizon"] == 1
    assert body["horizons"] == [1, 2]
    assert body["points"][0]["horizon"] == 1

    sql, params = fake_pool.cursor.queries[-1]
    assert "horizon = %s" in sql
    assert 1 in params


def test_daily_serves_the_requested_horizon(client, fake_pool):
    fake_pool.cursor.queue(_horizons(1, 2))
    fake_pool.cursor.queue([_row("model", horizon=2, topdecile_hit=0.7)])

    r = client.get("/scoreboard/daily", params={"run_id": "r", "horizon": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["horizon"] == 2
    assert body["points"][0]["horizon"] == 2
    assert 2 in fake_pool.cursor.queries[-1][1]


def test_daily_falls_back_to_the_only_graded_horizon(client, fake_pool):
    """A run that has only ever graded the preview track still serves it rather
    than 503-ing on an absent h1."""
    fake_pool.cursor.queue(_horizons(2))
    fake_pool.cursor.queue([_row("model", horizon=2, topdecile_hit=0.7)])

    r = client.get("/scoreboard/daily", params={"run_id": "r"})
    assert r.status_code == 200, r.text
    assert r.json()["horizon"] == 2


def test_daily_503_when_the_requested_horizon_has_no_grades(client, fake_pool):
    fake_pool.cursor.queue(_horizons(1))
    fake_pool.cursor.queue([])

    r = client.get("/scoreboard/daily", params={"run_id": "r", "horizon": 2})
    assert r.status_code == 503
    assert "horizon=2" in r.json()["detail"]
