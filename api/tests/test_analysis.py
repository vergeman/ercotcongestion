from datetime import date, timedelta

import pandas as pd
from fastapi import Query

from api.services.analysis import panels as analysis_module
from compute.analysis import brief_grade
from compute.analysis.hero_window import delivery_bounds
from compute.analysis.grade import GradeMetrics, GradeResult
from compute.projection.codecs import SfMuArtifact


def _artifact():
    return SfMuArtifact(
        SF=pd.DataFrame([[1.0]], index=["A|B"], columns=["SP"]),
        E_mu=pd.DataFrame([[4.0], [9.0]], index=pd.to_datetime([
            "2026-07-28T05:00Z", "2026-07-28T06:00Z"]), columns=["A|B"]),
    )


def _node_artifact():
    return SfMuArtifact(
        SF=pd.DataFrame([[1.0, 0.2], [-0.5, 1.0], [0.0, 0.4]],
                        index=["A|B", "C|D", "E|F"], columns=["SOURCE", "SINK"]),
        E_mu=pd.DataFrame([[4.0, 6.0, 2.0], [1.0, 3.0, 0.0]], index=pd.to_datetime([
            "2026-07-28T05:00Z", "2026-07-28T06:00Z"]), columns=["A|B", "C|D", "E|F"]),
    )


def test_brief_delivery_date_alias_resolves_to_the_canonical_name():
    delivery_date = date(2026, 7, 28)

    assert analysis_module._resolve_brief_delivery_date(delivery_date, None) == delivery_date
    assert analysis_module._resolve_brief_delivery_date(None, delivery_date) == delivery_date
    assert analysis_module._resolve_brief_delivery_date(Query(None), delivery_date) == delivery_date


def test_forecast_mu_profile_returns_the_artifacts_own_ct_day_hours(monkeypatch):
    """One artifact covers its whole CT day now (0133) — no cross-day stitch."""
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())

    result = analysis_module._forecast_mu_profile(None, "run-x", date(2026, 7, 28), 1)

    assert result is not None
    assert list(result.index) == list(pd.to_datetime(
        ["2026-07-28T05:00Z", "2026-07-28T06:00Z"], utc=True))


def test_forecast_mu_profile_is_none_when_the_artifact_is_missing(monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: None)

    assert analysis_module._forecast_mu_profile(None, "run-x", date(2026, 7, 28), 1) is None


def test_grade_constraint_profiles_stays_unavailable_when_the_artifact_is_missing(monkeypatch):
    """A missing artifact is the only unavailable case now (0133) — no partial-
    coverage gate to plant a fault in."""
    monkeypatch.setattr(brief_grade, "forecast_mu_profile", lambda *_: None)

    assert brief_grade.grade_constraint_profiles(None, "run-x", date(2026, 7, 28), 1) is None


def test_grade_node_profiles_stays_unavailable_when_the_artifact_is_missing(monkeypatch):
    monkeypatch.setattr(brief_grade, "_forecast_node_profile", lambda *_: None)

    assert brief_grade.grade_node_profiles(None, "run-x", date(2026, 7, 28), 1) is None


def test_windowed_mu_profiles_batches_the_trailing_window_into_per_day_frames(fake_pool):
    """0137: the trailing-window climatology fetch used to be one query per
    day (30 round trips); this asserts the batched replacement issues exactly
    one query and still splits the result into the same per-CT-day frames a
    30x loop of ``_settled_mu_profile`` would have produced."""
    fake_pool.cursor.queue([
        (pd.Timestamp("2026-07-26T05:00Z"), "A|B", 1.0),
        (pd.Timestamp("2026-07-26T06:00Z"), "A|B", 2.0),
        (pd.Timestamp("2026-07-27T05:00Z"), "A|B", 3.0),
        (pd.Timestamp("2026-07-27T06:00Z"), "A|B", 4.0),
    ])
    with fake_pool.connection() as conn:
        cur = conn.cursor(row_factory=None)
        by_day = analysis_module._windowed_mu_profiles(cur, date(2026, 7, 28), 2)

    assert len(fake_pool.cursor.queries) == 1
    assert set(by_day) == {date(2026, 7, 26), date(2026, 7, 27)}
    assert list(by_day[date(2026, 7, 26)]["A|B"]) == [1.0, 2.0]
    assert list(by_day[date(2026, 7, 27)]["A|B"]) == [3.0, 4.0]


def test_windowed_node_profiles_batches_the_trailing_window_into_per_day_frames(fake_pool):
    fake_pool.cursor.queue([
        (pd.Timestamp("2026-07-26T05:00Z"), "SP1", 1.0),
        (pd.Timestamp("2026-07-27T05:00Z"), "SP1", -2.0),
    ])
    with fake_pool.connection() as conn:
        cur = conn.cursor(row_factory=None)
        by_day = analysis_module._windowed_node_profiles(cur, date(2026, 7, 28), 2)

    assert len(fake_pool.cursor.queries) == 1
    assert set(by_day) == {date(2026, 7, 26), date(2026, 7, 27)}
    assert list(by_day[date(2026, 7, 26)]["SP1"]) == [1.0]
    assert list(by_day[date(2026, 7, 27)]["SP1"]) == [-2.0]


def _peak_hour_artifact(day: str):
    """A one-constraint artifact whose two hours land inside CT 7×16 (18:00Z ->
    13:00 CT, 19:00Z -> 14:00 CT), so ``_project_node_profile`` keeps both."""
    ts = pd.to_datetime([f"{day}T18:00Z", f"{day}T19:00Z"])
    return SfMuArtifact(
        SF=pd.DataFrame([[1.0, 0.2]], index=["A|B"], columns=["SOURCE", "SINK"]),
        E_mu=pd.DataFrame([[4.0], [6.0]], index=ts, columns=["A|B"]),
    )


def test_forecast_node_history_reads_forecast_nodal_in_one_query(fake_pool, monkeypatch):
    """0138: the trailing forecast node history is one ``forecast_nodal`` query
    (peak-hour mean per point/day) instead of decoding 30 prior-day artifacts.
    With every present day covered by the table, the artifact fallback finds
    nothing to add and no extra query is issued."""
    monkeypatch.setattr(analysis_module, "load_daily_artifacts", lambda *a, **k: {})
    fake_pool.cursor.queue([
        {"settlement_point": "SP1", "delivery_date": date(2026, 7, 26), "peak_mean": 3.0},
        {"settlement_point": "SP1", "delivery_date": date(2026, 7, 27), "peak_mean": 5.0},
        {"settlement_point": "SP2", "delivery_date": date(2026, 7, 27), "peak_mean": -2.0},
    ])
    with fake_pool.connection() as conn:
        cur = conn.cursor(row_factory=None)
        histories = analysis_module._forecast_node_history(cur, "run-x", date(2026, 7, 28), 1)

    assert len(fake_pool.cursor.queries) == 1
    assert sorted(histories["SP1"]) == [3.0, 5.0]
    assert histories["SP2"] == [-2.0]


def test_forecast_node_history_falls_back_to_artifact_for_absent_days(fake_pool, monkeypatch):
    """A trailing day missing from ``forecast_nodal`` degrades to projecting that
    day's artifact the old way (0138), so a coverage hole never silently drops a
    day from every node's baseline."""
    monkeypatch.setattr(
        analysis_module, "load_daily_artifacts",
        lambda cur, run_id, days, horizon: {date(2026, 7, 27): _peak_hour_artifact("2026-07-27")})
    fake_pool.cursor.queue([])  # forecast_nodal empty -> all 30 trailing days missing

    with fake_pool.connection() as conn:
        cur = conn.cursor(row_factory=None)
        histories = analysis_module._forecast_node_history(cur, "run-x", date(2026, 7, 28), 1)

    # -SF projection: SOURCE = -1.0*[4,6] -> mean -5.0; SINK = -0.2*[4,6] -> mean -1.0.
    assert histories["SOURCE"] == [-5.0]
    assert histories["SINK"] == [-1.0]


def test_trailing_settled_average_returns_none_when_a_trailing_day_is_missing():
    """A gap anywhere in the trailing window keeps the whole climatology
    unavailable — a partial baseline is not reported as a real one."""
    by_day = {date(2026, 7, 27): pd.DataFrame({"A|B": [1.0]})}  # day -1 only; -2 missing

    assert analysis_module._trailing_settled_average(date(2026, 7, 28), 1, by_day) is None


def _slots(basis):
    return {
        "magnitude": {"bucket": "near_top" if basis == "settled" else "ordinary"},
        "regime": {"bucket": "load_record_high"},
        "where": {"bucket": "concentrated", "zone": "south"},
        "exceptions": {"bucket": "none"},
    }


def test_hero_resolves_served_horizon_and_returns_forecast_segments(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"run_id": "run-x"}]) # published run
    fake_pool.cursor.queue([{"h": 1}])            # horizon resolve
    fake_pool.cursor.queue([{"ts": None}])        # DAM coverage
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))

    response = client.get("/analysis/hero?date=2026-07-28")
    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == {"run_id": "run-x", "delivery_date": "2026-07-28",
                                  "horizon": 1, "basis": "forecast"}
    assert body["verdict"] is None
    assert body["cursor"] == {"ws": "2026-07-28T05:00:00Z", "we": "2026-07-29T05:00:00Z",
                              "t": "2026-07-28T06:00:00Z"}
    assert all(part["ref"] in body["slots"] for group in body["segments"].values() for part in group)


def test_hero_settled_phase_grades_each_reconcilable_slot_independently(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": pd.Timestamp("2026-07-28T20:00Z")}])
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))

    body = client.get("/analysis/hero?date=2026-07-28").json()
    assert body["provenance"]["basis"] == "settled"
    assert body["verdict"] == {
        "magnitude": {"bucket": "under_called", "rungs": 3},
        "regime": None,
        "where": {"bucket": "held"},
        "exceptions": {"bucket": "held"},
    }


def test_hero_soft_fails_when_no_artifact_exists(client, fake_pool):
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"h": None}])
    body = client.get("/analysis/hero?date=2026-07-28").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing",
                    "run_id": "run-x", "delivery_date": "2026-07-28"}


def test_hero_latest_returns_the_newest_published_day(client, fake_pool):
    """One artifact covers its whole CT day now (0133) — no following-day join."""
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"delivery_date": date(2026, 7, 28), "horizon": 1}])

    body = client.get("/analysis/hero/latest").json()

    assert body == {"available": True, "run_id": "run-x", "delivery_date": "2026-07-28", "horizon": 1}
    sql, params = fake_pool.cursor.queries[-1]
    assert "following" not in sql
    assert params == ("run-x",)


def test_hero_latest_soft_fails_without_any_published_day(client, fake_pool):
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([])

    assert client.get("/analysis/hero/latest").json() == {
        "available": False, "run_id": "run-x", "delivery_date": None, "horizon": None,
    }


def test_brief_day_composes_all_sections_from_one_resolved_run_and_horizon(client, fake_pool, monkeypatch):
    """0137: the bundled endpoint resolves run/horizon once, then delegates to
    each section's own handler — never re-derives their query logic.

    Each handler is called in-process, bypassing FastAPI's dependency
    injection, so any parameter left to its declared default would instead
    receive that default's raw ``Query(...)`` object. This asserts the exact
    positional args every handler receives, so a call missing an explicit
    literal (as `get_context`'s `chronic_limit` once did) fails loudly instead
    of silently handing a `Query` sentinel to `chronic[:chronic_limit]`.

    The handlers run on a thread pool (not sequentially), so `calls` below is
    keyed by name rather than compared in submission order.
    """
    fake_pool.cursor.queue([{"run_id": "run-x"}])  # resolve run
    fake_pool.cursor.queue([{"h": 2}])              # resolve horizon

    calls: dict[str, tuple] = {}

    def _handler(name):
        def _fake(delivery_date, run_id, horizon, *rest):
            calls[name] = (delivery_date, run_id, horizon, rest)
            return {"available": False, "unavailable_reason": "artifact_missing",
                    "run_id": run_id, "delivery_date": delivery_date, "horizon": horizon}
        return _fake

    # (handler name, expected trailing positional args — each must be a
    # literal, matching that endpoint's own Query(...) default exactly).
    expected = (
        ("get_hero", ()),
        ("get_context", (14,)),
        ("get_standouts", (4,)),
        ("get_top_nodes", (10,)),
        ("get_top_constraints", (10,)),
        ("get_grade", ()),
        ("get_grade_history", (30,)),
    )
    for name, _ in expected:
        monkeypatch.setattr(analysis_module, name, _handler(name))

    response = client.get("/analysis/brief?day=2026-07-28")

    assert response.status_code == 200
    assert calls == {
        name: (date(2026, 7, 28), "run-x", 2, rest) for name, rest in expected
    }
    for _, _, _, rest in calls.values():
        assert all(isinstance(value, int) for value in rest), \
            "a trailing arg fell through to its raw Query(...) default"
    body = response.json()
    assert set(body.keys()) == {"hero", "context", "standouts", "top_nodes",
                                "top_constraints", "grade", "grade_history"}


def test_brief_hero_shell_returns_navigation_without_running_detail_handlers(
    client, fake_pool, monkeypatch,
):
    """First paint is hero-only; date carets use two cheap artifact lookups."""
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"h": 2}])
    fake_pool.cursor.queue([{"delivery_date": date(2026, 7, 27)}])
    fake_pool.cursor.queue([{"delivery_date": date(2026, 7, 29)}])
    calls = {"hero": 0, "include_condition": None}

    def hero(*_args, **_kwargs):
        calls["hero"] += 1
        calls["include_condition"] = _kwargs.get("include_condition")
        return {"available": False, "unavailable_reason": "artifact_missing",
                "run_id": "run-x", "delivery_date": date(2026, 7, 28), "horizon": 2}

    monkeypatch.setattr(analysis_module, "get_hero", hero)
    for name in ("get_context", "get_standouts", "get_top_nodes", "get_top_constraints",
                 "get_grade", "get_grade_history"):
        monkeypatch.setattr(
            analysis_module, name,
            lambda *_: (_ for _ in ()).throw(AssertionError("detail handler ran")),
        )

    body = client.get("/analysis/brief/hero?day=2026-07-28").json()

    assert calls == {"hero": 1, "include_condition": False}
    assert body == {
        "hero": {"available": False, "unavailable_reason": "artifact_missing",
                 "run_id": "run-x", "delivery_date": "2026-07-28", "horizon": 2},
        "previous_delivery_date": "2026-07-27",
        "next_delivery_date": "2026-07-29",
    }


def test_brief_hero_stats_returns_all_card_slots_in_one_response(
    client, fake_pool, monkeypatch,
):
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"h": 2}])
    monkeypatch.setattr(
        analysis_module,
        "get_hero",
        lambda *_args, **_kwargs: {
            "available": True,
            "slots": {"regime": {"today": 84_000.0}, "magnitude": {"rank": 3},
                      "where": {"zone": "north"}},
            "provenance": {"basis": "forecast"},
        },
    )

    body = client.get("/analysis/brief/hero/stats?day=2026-07-28").json()

    assert body == {
        "run_id": "run-x", "delivery_date": "2026-07-28", "horizon": 2,
        "slots": {"regime": {"today": 84_000.0}, "magnitude": {"rank": 3},
                  "where": {"zone": "north"}},
    }


def test_brief_details_composes_every_secondary_panel_but_not_hero(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"h": 2}])
    calls: set[str] = set()

    def detail(name):
        def handler(delivery_date, run_id, horizon, *_rest):
            calls.add(name)
            return {"available": False, "unavailable_reason": "artifact_missing",
                    "run_id": run_id, "delivery_date": delivery_date, "horizon": horizon}
        return handler

    monkeypatch.setattr(
        analysis_module, "get_hero",
        lambda *_: (_ for _ in ()).throw(AssertionError("hero handler ran")),
    )
    names = ("get_context", "get_standouts", "get_top_nodes", "get_top_constraints",
             "get_grade", "get_grade_history")
    for name in names:
        monkeypatch.setattr(analysis_module, name, detail(name))

    response = client.get("/analysis/brief/details?day=2026-07-28")

    assert response.status_code == 200
    assert calls == set(names)
    assert set(response.json()) == {
        "context", "standouts", "top_nodes", "top_constraints", "grade", "grade_history",
    }


def _brief_section_counter(monkeypatch):
    """Monkeypatch the seven /brief section handlers to count invocations."""
    calls = {"n": 0}

    def _handler():
        def _fake(delivery_date, run_id, horizon, *rest):
            calls["n"] += 1
            return {"available": False, "unavailable_reason": "artifact_missing",
                    "run_id": run_id, "delivery_date": delivery_date, "horizon": horizon}
        return _fake

    for name in ("get_hero", "get_context", "get_standouts", "get_top_nodes",
                 "get_top_constraints", "get_grade", "get_grade_history"):
        monkeypatch.setattr(analysis_module, name, _handler())
    return calls


def test_brief_caches_a_settled_day(client, fake_pool, monkeypatch):
    """A past final day (horizon 1, DAM landed) composes once, then serves from
    the response cache — the sections are not re-invoked."""
    _, we = delivery_bounds(date(2026, 7, 28))  # DAM ts past the day's midpoint
    calls = _brief_section_counter(monkeypatch)
    for _ in range(2):  # run + horizon + dam-landed probe, per request
        fake_pool.cursor.queue([{"run_id": "run-x"}])
        fake_pool.cursor.queue([{"h": 1}])
        fake_pool.cursor.queue([{"ts": we}])

    first = client.get("/analysis/brief?day=2026-07-28")
    second = client.get("/analysis/brief?day=2026-07-28")

    assert first.status_code == 200 and second.status_code == 200
    assert first.content == second.content
    assert calls["n"] == 7, "settled day should compose once, then hit the cache"


def test_brief_recomputes_an_unsettled_day(client, fake_pool, monkeypatch):
    """A day whose DAM has not landed is never cached, so it is never served
    stale before its inputs settle."""
    calls = _brief_section_counter(monkeypatch)
    for _ in range(2):
        fake_pool.cursor.queue([{"run_id": "run-x"}])
        fake_pool.cursor.queue([{"h": 1}])
        fake_pool.cursor.queue([{"ts": None}])  # DAM not landed -> not final

    client.get("/analysis/brief?day=2026-07-28")
    client.get("/analysis/brief?day=2026-07-28")

    assert calls["n"] == 14, "unsettled day recomputes every request (7 sections x 2)"


def test_hero_declares_a_typed_available_or_soft_fail_contract(client):
    schema = client.app.openapi()["paths"]["/analysis/hero"]["get"]["responses"]["200"]
    names = {item["$ref"].rsplit("/", 1)[-1] for item in schema["content"]["application/json"]
             ["schema"]["anyOf"]}
    assert names == {"HeroAvailableResponse", "HeroUnavailableResponse",
                     "HeroUnavailableAtHorizonResponse"}


def test_hero_repeats_byte_identically_for_unchanged_inputs(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": None}])
    fake_pool.cursor.queue([{"run_id": "run-x"}])
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": None}])
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))
    first = client.get("/analysis/hero?date=2026-07-28")
    second = client.get("/analysis/hero?date=2026-07-28")
    assert first.content == second.content


def test_joined_top_keys_orders_dam_leaders_then_forecast_only_leaders():
    forecast = pd.Index(["forecast-1", "both", "forecast-3", "forecast-4"])
    settled = pd.Index(["settled-1", "both", "settled-3"])

    assert analysis_module._joined_top_keys(
        forecast, settled, k=3, settled_available=False,
    ) == ["forecast-1", "both", "forecast-3"]
    assert analysis_module._joined_top_keys(
        forecast, settled, k=3, settled_available=True,
    ) == ["settled-1", "both", "settled-3", "forecast-1", "forecast-3"]


def test_standouts_compare_forecast_to_own_forecast_history_and_keep_dam_as_evidence():
    rows = analysis_module._standout_rows(
        pd.Series({"ELEVATED": 300.0, "CHRONIC": 10.0, "ORDINARY": 100.0}),
        {
            "ELEVATED": [100.0] * 30,
            "CHRONIC": [100.0] * 30,
            "ORDINARY": [100.0] * 30,
        },
        {"CHRONIC": 28},
        pd.Series({"ELEVATED": 250.0, "CHRONIC": 400.0}),
        k=1,
    )

    assert [row.constraint_key for row in rows] == ["ELEVATED", "CHRONIC"]
    assert [row.kind for row in rows] == ["forecast_elevated", "chronic_under_called"]
    assert rows[0].settled_total == 250.0
    assert rows[1].settled_total == 400.0


def test_settled_standouts_append_only_dam_surprises_not_already_shown_forecasts():
    keys = analysis_module._settled_standout_keys(
        pd.Series({"FORECAST_ROW": 500.0, "DAM_SURPRISE": 300.0, "ORDINARY": 110.0}),
        {
            "FORECAST_ROW": [100.0] * 30,
            "DAM_SURPRISE": [100.0] * 30,
            "ORDINARY": [100.0] * 30,
        },
        {"FORECAST_ROW"}, k=3,
    )

    assert keys == ["DAM_SURPRISE"]


def test_settled_node_standouts_append_dam_surprises_not_forecast_rows():
    keys = analysis_module._settled_node_standout_keys(
        pd.Series({"FORECAST_NODE": 50.0, "DAM_NODE": -40.0, "ORDINARY": 11.0}),
        {
            "FORECAST_NODE": [10.0] * 30,
            "DAM_NODE": [10.0] * 30,
            "ORDINARY": [10.0] * 30,
        },
        {"FORECAST_NODE"}, k=3,
    )

    assert keys == ["DAM_NODE"]


def test_node_returns_the_full_column_and_coverage(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    timestamps = list(artifact.E_mu.index.to_pydatetime())
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([
        {"interval_ts": timestamps[0], "settlement_point": "SOURCE", "dam_spp": 42.0},
        {"interval_ts": timestamps[1], "settlement_point": "SOURCE", "dam_spp": 38.0},
    ])
    fake_pool.cursor.queue([
        {"interval_ts": timestamps[0], "system_lambda": 30.0},
        {"interval_ts": timestamps[1], "system_lambda": 30.0},
    ])

    body = client.get("/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body["available"] is True
    assert [row["constraint_key"] for row in body["terms"]] == ["A|B", "C|D"]
    assert body["n_terms"] == 2
    assert body["total"] == -0.5
    assert body["coverage"] == -0.025


def test_node_realized_basis_keeps_sf_shape_and_swaps_mu(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    timestamps = list(artifact.E_mu.index.to_pydatetime())
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([
        {"interval_ts": timestamps[0], "constraint_name": "A", "contingency_name": "B", "shadow_price": 10.0},
        {"interval_ts": timestamps[1], "constraint_name": "C", "contingency_name": "D", "shadow_price": 1.0},
    ])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])

    body = client.get("/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
                      "&basis=realized&run_id=run-x&horizon=1").json()
    assert {row["constraint_key"] for row in body["terms"]} == {"A|B", "C|D"}
    assert body["total"] == -9.5


def test_node_single_hour_predicted_uses_only_that_hours_forecast_mu(client, fake_pool, monkeypatch):
    """The scrubbed hour (05:00Z = CT midnight on the summer boundary — the
    artifact's first hour, mirroring ``matrix.py::_delivery_date``) must
    resolve to exactly its own ``E_mu`` row, not the whole-day sum."""
    artifact = _node_artifact()
    ts0 = artifact.E_mu.index[0].to_pydatetime()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([])  # settled congestion: SPP
    fake_pool.cursor.queue([])  # settled congestion: system lambda

    body = client.get(f"/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
                      f"&basis=predicted&run_id=run-x&horizon=1&hours={ts0.isoformat().replace('+00:00', 'Z')}").json()

    assert body["available"] is True
    assert body["hours"] == ["2026-07-28T05:00:00Z"]
    assert [row["constraint_key"] for row in body["terms"]] == ["A|B", "C|D"]
    assert body["n_terms"] == 2
    assert body["total"] == -1.0


def test_node_single_hour_includes_market_state(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    ts0 = artifact.E_mu.index[0].to_pydatetime()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([])  # coverage: settled SPP
    fake_pool.cursor.queue([])  # coverage: settled lambda
    fake_pool.cursor.queue([{"point": 5.0}])
    fake_pool.cursor.queue([{"interval_ts": ts0, "system_lambda": 30.0}])
    fake_pool.cursor.queue([{"dam_spp": 35.0}])

    body = client.get(
        f"/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
        f"&basis=predicted&run_id=run-x&horizon=1&hours={ts0.isoformat().replace('+00:00', 'Z')}"
    ).json()

    assert body["market_state"] == {
        "forecast_congestion": 5.0,
        "forecast_lmp": 35.0,
        "realized_congestion": 5.0,
        "forecast_error": 0.0,
        "dam_lmp": 35.0,
        "forecast_lambda_source": "settled",
    }


def test_node_detail_expansion_combines_structural_terms_and_essp_count(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    ts0 = artifact.E_mu.index[0].to_pydatetime()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([])  # coverage: settled SPP
    fake_pool.cursor.queue([])  # coverage: settled lambda
    fake_pool.cursor.queue([{"point": 5.0}])
    fake_pool.cursor.queue([{"interval_ts": ts0, "system_lambda": 30.0}])
    fake_pool.cursor.queue([{"dam_spp": 35.0}])
    fake_pool.cursor.queue([{"member_count": 3}])

    body = client.get(
        f"/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
        f"&basis=predicted&run_id=run-x&horizon=1&include_detail=true"
        f"&hours={ts0.isoformat().replace('+00:00', 'Z')}"
    ).json()

    assert [term["constraint_key"] for term in body["terms"]] == ["A|B", "C|D"]
    assert body["structural_n_terms"] == 2
    assert [term["constraint_key"] for term in body["structural_terms"]] == ["A|B", "C|D"]
    assert body["essp_member_count"] == 3


def test_node_market_state_keeps_missing_values_null(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    ts0 = artifact.E_mu.index[0].to_pydatetime()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([])  # coverage: settled SPP
    fake_pool.cursor.queue([])  # coverage: settled lambda
    fake_pool.cursor.queue([])  # forecast P50
    fake_pool.cursor.queue([])  # exact forecast lambda
    fake_pool.cursor.queue([])  # DAM SPP

    body = client.get(
        f"/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
        f"&basis=predicted&run_id=run-x&horizon=1&hours={ts0.isoformat().replace('+00:00', 'Z')}"
    ).json()

    assert body["market_state"] == {
        "forecast_congestion": None,
        "forecast_lmp": None,
        "realized_congestion": None,
        "forecast_error": None,
        "dam_lmp": None,
        "forecast_lambda_source": None,
    }


def test_node_market_state_uses_persisted_forecast_lambda(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    ts0 = artifact.E_mu.index[0].to_pydatetime()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([])  # coverage: settled SPP
    fake_pool.cursor.queue([])  # coverage: settled lambda
    fake_pool.cursor.queue([{"point": 5.0}])
    fake_pool.cursor.queue([])  # exact forecast lambda is not yet published
    fake_pool.cursor.queue([{"interval_ts": ts0, "system_lambda": 25.0}])
    fake_pool.cursor.queue([])  # DAM SPP is not yet published

    body = client.get(
        f"/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
        f"&basis=predicted&run_id=run-x&horizon=1&hours={ts0.isoformat().replace('+00:00', 'Z')}"
    ).json()

    assert body["market_state"] == {
        "forecast_congestion": 5.0,
        "forecast_lmp": 30.0,
        "realized_congestion": None,
        "forecast_error": None,
        "dam_lmp": None,
        "forecast_lambda_source": "persisted",
    }


def test_node_single_hour_realized_uses_only_that_hours_dam_mu(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    ts0 = artifact.E_mu.index[0].to_pydatetime()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([
        {"interval_ts": ts0, "constraint_name": "C", "contingency_name": "D", "shadow_price": 8.0},
    ])
    fake_pool.cursor.queue([])  # settled congestion: SPP
    fake_pool.cursor.queue([])  # settled congestion: system lambda

    body = client.get(f"/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
                      f"&basis=realized&run_id=run-x&horizon=1&hours={ts0.isoformat().replace('+00:00', 'Z')}").json()

    assert body["available"] is True
    assert body["hours"] == ["2026-07-28T05:00:00Z"]
    assert [row["constraint_key"] for row in body["terms"]] == ["C|D"]
    assert body["n_terms"] == 1
    assert body["total"] == 4.0


def test_node_soft_fails_when_artifact_is_unavailable(client, fake_pool, monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: None)
    body = client.get("/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing", "run_id": "run-x",
                    "delivery_date": "2026-07-28", "horizon": 1}


def test_settlement_points_returns_the_artifact_vocabulary_not_a_matrix_screen(client, fake_pool, monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _node_artifact())
    monkeypatch.setattr(analysis_module, "load_sp_metadata", lambda _: {
        "SINK": {"sp_type": "load_zone", "load_zone": "west", "lat": 31.2, "lon": -101.5},
        "SOURCE": {"sp_type": "resource", "load_zone": "north", "lat": None, "lon": None},
    })
    body = client.get("/analysis/settlement-points?delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body == {"available": True, "run_id": "run-x", "delivery_date": "2026-07-28",
                    "horizon": 1, "settlement_points": ["SINK", "SOURCE"],
                    "metadata": [
                        {"settlement_point": "SINK", "settlement_point_type": "load_zone", "load_zone": "west", "lat": 31.2, "lon": -101.5},
                        {"settlement_point": "SOURCE", "settlement_point_type": "resource", "load_zone": "north", "lat": None, "lon": None},
                    ]}


def test_settlement_points_soft_fails_with_its_declared_model(client, fake_pool, monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: None)
    body = client.get("/analysis/settlement-points?delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing", "run_id": "run-x",
                    "delivery_date": "2026-07-28", "horizon": 1}


def test_constraints_returns_the_full_vocabulary_ranked_by_mu_mass(client, fake_pool, monkeypatch):
    """Every artifact constraint is returned — not a top-k Brief cast — ordered
    by Σ|E_mu| with best-effort constraint_geo metadata folded in per key."""
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _node_artifact())
    fake_pool.cursor.queue([
        {"constraint_key": "A|B", "ctype": "radial", "zone_shares": {"south": 0.6, "north": 0.4},
         "kv_max": 345.0},
    ])

    body = client.get("/analysis/constraints?delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()

    assert body["available"] is True
    assert body["n_total"] == 3
    assert body["rows"] == [
        {"constraint_key": "C|D", "name": "C", "contingency": "D", "ctype": None,
         "zone": None, "kv_max": None, "binding_hours": 2, "daily_mu_rank": 1,
         "daily_mu_sum": 9.0},
        {"constraint_key": "A|B", "name": "A", "contingency": "B", "ctype": "radial",
         "zone": "south", "kv_max": 345.0, "binding_hours": 2, "daily_mu_rank": 2,
         "daily_mu_sum": 5.0},
        {"constraint_key": "E|F", "name": "E", "contingency": "F", "ctype": None,
         "zone": None, "kv_max": None, "binding_hours": 1, "daily_mu_rank": 3,
         "daily_mu_sum": 2.0},
    ]


def test_constraints_soft_fails_when_artifact_is_unavailable(client, fake_pool, monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: None)
    body = client.get("/analysis/constraints?delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing", "run_id": "run-x",
                    "delivery_date": "2026-07-28", "horizon": 1}


def test_node_structural_mode_includes_quiet_nonzero_sf_terms(client, fake_pool, monkeypatch):
    artifact = SfMuArtifact(
        SF=pd.DataFrame([[1.0], [0.5]], index=["ACTIVE|C", "QUIET|C"], columns=["SOURCE"]),
        E_mu=pd.DataFrame([[4.0, 0.0]], index=pd.to_datetime(["2026-07-28T05:00Z"]),
                          columns=["ACTIVE|C", "QUIET|C"]),
    )
    ts0 = artifact.E_mu.index[0].to_pydatetime()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    fake_pool.cursor.queue([])  # coverage: settled SPP
    fake_pool.cursor.queue([])  # coverage: settled lambda
    fake_pool.cursor.queue([])  # forecast P50
    fake_pool.cursor.queue([])  # exact forecast lambda
    fake_pool.cursor.queue([])  # DAM SPP

    body = client.get(
        "/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
        f"&basis=predicted&run_id=run-x&horizon=1&mode=structural&hours={ts0.isoformat().replace('+00:00', 'Z')}"
    ).json()

    assert body["n_terms"] == 2
    assert body["terms"] == [
        {"constraint_key": "ACTIVE|C", "contribution": -4.0, "shift_factor": 1.0},
        {"constraint_key": "QUIET|C", "contribution": 0.0, "shift_factor": 0.5},
    ]


def test_essp_returns_hourly_membership_for_requested_vintage(client, fake_pool):
    fake_pool.cursor.queue([
        {"group_index": 7, "settlement_points": ["ALPHA", "BETA"]},
        {"group_index": 19, "settlement_points": ["GAMMA", "OMEGA"]},
    ])
    body = client.get("/analysis/essp?interval_ts=2026-07-28T16:00:00Z&source=study").json()
    assert body == {
        "available": True, "interval_ts": "2026-07-28T16:00:00Z", "source": "study",
        "groups": [
            {"group_index": 7, "settlement_points": ["ALPHA", "BETA"]},
            {"group_index": 19, "settlement_points": ["GAMMA", "OMEGA"]},
        ],
    }
    sql, params = fake_pool.cursor.queries[-1]
    assert "FROM ercot_essp" in sql
    assert params[1] is True


def test_essp_soft_fails_without_a_cross_day_or_cross_vintage_fallback(client, fake_pool):
    fake_pool.cursor.queue([])
    body = client.get("/analysis/essp?interval_ts=2026-07-28T16:00:00Z&source=final").json()
    assert body == {"available": False, "unavailable_reason": "essp_missing",
                    "interval_ts": "2026-07-28T16:00:00Z", "source": "final"}
    assert fake_pool.cursor.queries[-1][1][1] is False


def test_essp_requires_an_offset_unambiguous_hour(client):
    response = client.get("/analysis/essp?interval_ts=2026-07-28T16:00:00")
    assert response.status_code == 422
    assert response.json()["detail"] == "interval_ts must include a UTC offset."


def test_grade_returns_unblended_constraint_and_node_halves(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"h": 1}])
    metrics = GradeMetrics(detection_ap=0.62, magnitude_overlap=0.50,
                           timing_daily_skill=0.55, timing_hourly_skill=0.34)
    result = GradeResult(universe=("A|B", "C|D"), model=metrics, persistence=metrics)
    monkeypatch.setattr(analysis_module, "_settled_mu_profile", lambda *_: pd.DataFrame([[0.0]]))
    monkeypatch.setattr(analysis_module, "_brief_grade_constraint_profiles", lambda *_: result)
    monkeypatch.setattr(analysis_module, "_brief_grade_node_profiles", lambda *_: result)

    body = client.get("/analysis/grade?delivery_date=2026-07-28&run_id=run-x").json()

    assert body["available"] is True
    assert {key: body["constraints"][key] for key in ("graded", "unavailable_reason", "universe_size",
                                                        "model", "persistence", "climatology", "support")} == {
        "graded": True, "unavailable_reason": None, "universe_size": 2,
        "model": {"detection_ap": 0.62, "magnitude_overlap": 0.5,
                  "timing_daily_skill": 0.55, "timing_hourly_skill": 0.34,
                  "top_decile_daily_capture": None, "top_decile_hourly_capture": None},
        "persistence": {"detection_ap": 0.62, "magnitude_overlap": 0.5,
                        "timing_daily_skill": 0.55, "timing_hourly_skill": 0.34,
                        "top_decile_daily_capture": None, "top_decile_hourly_capture": None},
        "climatology": None,
        "support": None,
    }
    assert {key: body["nodes"][key] for key in ("graded", "unavailable_reason", "universe_size",
                                                  "model", "persistence", "climatology", "support")} == {
        "graded": True, "unavailable_reason": None, "universe_size": 2,
        "model": {"detection_ap": 0.62, "magnitude_overlap": 0.5,
                  "timing_daily_skill": 0.55, "timing_hourly_skill": 0.34,
                  "top_decile_daily_capture": None, "top_decile_hourly_capture": None},
        "persistence": {"detection_ap": 0.62, "magnitude_overlap": 0.5,
                        "timing_daily_skill": 0.55, "timing_hourly_skill": 0.34,
                        "top_decile_daily_capture": None, "top_decile_hourly_capture": None},
        "climatology": None,
        "support": None,
    }
    assert [item["id"] for item in body["constraints"]["sources"]] == [
        "brief_model_artifact_profile", "brief_persistence_prior_settled_profile",
    ]
    assert "grade" not in body


def test_grade_response_wraps_the_compute_neutral_result(fake_pool, monkeypatch):
    """The API owns its response model while compute owns grade serialization."""
    metrics = GradeMetrics(detection_ap=0.62, magnitude_overlap=0.50,
                           timing_daily_skill=0.55, timing_hourly_skill=0.34)
    result = GradeResult(universe=("A|B", "C|D"), model=metrics, persistence=metrics)
    monkeypatch.setattr(analysis_module, "_settled_mu_profile",
                        lambda *_: pd.DataFrame([[0.0]]))
    monkeypatch.setattr(analysis_module, "_brief_grade_constraint_profiles", lambda *_: result)
    monkeypatch.setattr(analysis_module, "_brief_grade_node_profiles", lambda *_: result)
    fake_pool.cursor.queue([])  # no materialized snapshot: compute must score it.

    response = analysis_module.get_grade(date(2026, 7, 28), "run-x", 1)

    body = response.model_dump(mode="json")
    assert {key: body[key] for key in ("available", "run_id", "delivery_date", "horizon")} == {
        "available": True, "run_id": "run-x", "delivery_date": "2026-07-28", "horizon": 1,
    }
    assert body["constraints"]["source_metrics"][0]["id"] == "brief_model_artifact_profile"


def test_grade_uses_the_materialized_snapshot_without_recomputing(client, fake_pool, monkeypatch):
    metrics = {"detection_ap": 0.62, "magnitude_overlap": 0.50,
               "timing_daily_skill": 0.55, "timing_hourly_skill": 0.34,
               "top_decile_daily_capture": None, "top_decile_hourly_capture": None}
    detail = {"graded": True, "unavailable_reason": None, "universe_size": 2,
              "model": metrics, "persistence": metrics, "climatology": None, "support": None}
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([
        {"subject": "constraints", "detail": detail},
        {"subject": "nodes", "detail": detail},
    ])
    monkeypatch.setattr(analysis_module, "_settled_mu_profile", lambda *_: pd.DataFrame([[0.0]]))
    monkeypatch.setattr(analysis_module, "_brief_grade_constraint_profiles",
                        lambda *_: (_ for _ in ()).throw(AssertionError("should not recompute")))

    body = client.get("/analysis/grade?delivery_date=2026-07-28&run_id=run-x").json()

    assert {key: body["constraints"][key] for key in detail} == detail
    assert {key: body["nodes"][key] for key in detail} == detail
    assert body["constraints"]["sources"][0]["id"] == "brief_model_artifact_profile"


def test_grade_soft_fails_when_the_served_artifact_horizon_is_missing(client, fake_pool):
    fake_pool.cursor.queue([{"h": None}])

    body = client.get("/analysis/grade?delivery_date=2026-07-28&run_id=run-x").json()

    assert body == {"available": False, "unavailable_reason": "artifact_missing", "run_id": "run-x",
                    "delivery_date": "2026-07-28", "horizon": None}


def _repeated_window(delivery_date, frame) -> dict:
    """The climatology window a mocked ``_settled_node_profile``/``_settled_mu_profile``
    used to produce implicitly (30 identical trailing days) — now built explicitly
    since the batched ``_windowed_*_profiles`` fetch (0137) isn't covered by
    mocking those single-day loaders anymore."""
    return {delivery_date - timedelta(days=offset): frame for offset in range(1, 31)}


def test_node_grade_uses_absolute_congestion_so_opposite_sides_cannot_net(monkeypatch):
    hours = pd.RangeIndex(2)
    forecast = pd.DataFrame({"IMPORT": [-1.0, -1.0], "EXPORT": [1.0, 1.0]}, index=hours)
    settled = pd.DataFrame({"IMPORT": [-10.0, -10.0], "EXPORT": [10.0, 10.0]}, index=hours)
    monkeypatch.setattr(brief_grade, "_forecast_node_profile", lambda *_: forecast)
    monkeypatch.setattr(brief_grade, "_settled_node_profile", lambda *_: settled)
    monkeypatch.setattr(brief_grade, "_windowed_profiles",
                        lambda *_, **__: _repeated_window(date(2026, 7, 28), settled))

    grade = brief_grade.grade_node_profiles(None, "run-x", date(2026, 7, 28), 1)

    assert grade is not None
    assert grade.model.magnitude_overlap == 2 / 11


def test_node_grade_uses_epsilon_only_to_discard_float_residue(monkeypatch):
    hours = pd.RangeIndex(2)
    forecast = pd.DataFrame({"REAL": [0.001, 0.0], "NOISE": [0.0, 0.0]}, index=hours)
    settled = pd.DataFrame({"REAL": [0.001, 0.0], "NOISE": [5e-7, 0.0]}, index=hours)
    monkeypatch.setattr(brief_grade, "_forecast_node_profile", lambda *_: forecast)
    monkeypatch.setattr(brief_grade, "_settled_node_profile", lambda *_: settled)
    monkeypatch.setattr(brief_grade, "_windowed_profiles",
                        lambda *_, **__: _repeated_window(date(2026, 7, 28), settled))

    grade = brief_grade.grade_node_profiles(None, "run-x", date(2026, 7, 28), 1)

    assert grade is not None
    assert grade.model.detection_ap == 1.0
    assert grade.model.top_decile_daily_capture == 1.0
    assert grade.model.top_decile_hourly_capture == 1.0
    assert grade.model.timing_daily_skill == 1.0
