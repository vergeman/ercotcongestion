"""Map scorecard source selection."""

from datetime import date

from api.services.map import scorecard


DAY = date(2026, 7, 1)


def _daily(source: str, **extra):
    return {"run_id": "served-v1", "source": source, **extra}


def _weekly(source: str, week=date(2026, 6, 29), **extra):
    return {"run_id": "backtest-v1", "week": week, "source": source, **extra}


def _metrics(rows):
    return [
        {"rank_spearman": 0.4, "sign_agree": 0.5, "topdecile_hit": 0.6, **row}
        for row in rows
    ]


def test_final_h1_scorecard_is_preferred_and_normalized(fake_pool):
    fake_pool.cursor.queue(_metrics([
        _daily("scoreboard_model_served_nodal"),
        _daily("scoreboard_persistence_prior_day_nodal"),
        _daily("scoreboard_oracle_settled_mu_nodal"),
        {**_daily("scoreboard_model_served_nodal"), "run_id": "preview-v1"},
    ]))

    result = scorecard.build(DAY)

    assert result.available is True
    assert result.basis == "served_daily"
    assert result.delivery_date == DAY and result.horizon == 1
    assert [(source.series_id, source.source_id) for source in result.sources] == [
        ("model", "scoreboard_model_served_nodal"),
        ("persistence", "scoreboard_persistence_prior_day_nodal"),
        ("oracle", "scoreboard_oracle_settled_mu_nodal"),
    ]
    assert len(fake_pool.cursor.queries) == 1
    assert "horizon = 1" in fake_pool.cursor.queries[0][0]
    assert fake_pool.cursor.queries[0][1][0] == DAY


def test_h2_rows_are_excluded_before_weekly_fallback(fake_pool):
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue(_metrics([
        _weekly("scoreboard_model_backtest_nodal"),
        _weekly("scoreboard_persistence_backtest_nodal"),
        _weekly("scoreboard_oracle_backtest_nodal"),
    ]))

    result = scorecard.build(DAY)

    assert result.basis == "weekly_backtest_fallback"
    assert result.horizon is None
    assert "horizon = 1" in fake_pool.cursor.queries[0][0]


def test_incomplete_daily_set_falls_back_without_blending(fake_pool):
    fake_pool.cursor.queue(_metrics([
        _daily("scoreboard_model_served_nodal"),
        _daily("scoreboard_persistence_prior_day_nodal"),
    ]))
    fake_pool.cursor.queue(_metrics([
        _weekly("scoreboard_model_backtest_nodal", week=date(2026, 6, 22)),
        _weekly("scoreboard_persistence_backtest_nodal", week=date(2026, 6, 22)),
        _weekly("scoreboard_oracle_backtest_nodal", week=date(2026, 6, 22)),
        _weekly("scoreboard_model_backtest_nodal"),
        _weekly("scoreboard_persistence_backtest_nodal"),
    ]))

    result = scorecard.build(DAY)

    assert result.basis == "weekly_backtest_fallback"
    assert result.scored_week == date(2026, 6, 22)
    assert all("backtest" in source.source_id for source in result.sources)


def test_returns_explicit_unavailable_when_no_complete_set_exists(fake_pool):
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])

    result = scorecard.build(DAY)

    assert result.model_dump() == {
        "available": False,
        "unavailable_reason": "no_complete_scorecard",
        "basis": None,
        "run_id": None,
        "delivery_date": DAY,
        "scored_week": None,
        "horizon": None,
        "sources": [],
    }


def test_route_uses_supplied_ct_delivery_date(client, monkeypatch):
    seen = []
    monkeypatch.setattr(scorecard, "build", lambda day: seen.append(day) or {
        "available": False, "delivery_date": day,
    })

    response = client.get("/map/scorecard?day=2026-07-01")

    assert response.status_code == 200
    assert seen == [DAY]
