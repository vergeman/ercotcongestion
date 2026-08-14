from datetime import date

import pandas as pd

import analysis as analysis_module
from compute.analysis.brief import nodal_congestion
from compute.analysis.grade import GradeMetrics, GradeResult
from compute.sf.project import SfMuArtifact


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


def _slots(basis):
    return {
        "magnitude": {"bucket": "near_top" if basis == "settled" else "ordinary"},
        "regime": {"bucket": "load_record_high"},
        "where": {"bucket": "concentrated", "zone": "south"},
        "exceptions": {"bucket": "none"},
    }


def test_hero_resolves_served_horizon_and_returns_forecast_segments(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"h": 1}])            # horizon resolve
    fake_pool.cursor.queue([{"ts": None}])        # DAM coverage
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))

    response = client.get("/analysis/hero?date=2026-07-28&run_id=run-x")
    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == {"run_id": "run-x", "delivery_date": "2026-07-28",
                                  "horizon": 1, "basis": "forecast"}
    assert body["verdict"] is None
    assert body["cursor"] == {"ws": "2026-07-28T05:00:00Z", "we": "2026-07-29T05:00:00Z",
                              "t": "2026-07-28T06:00:00Z"}
    assert all(part["ref"] in body["slots"] for group in body["segments"].values() for part in group)


def test_hero_settled_phase_grades_each_reconcilable_slot_independently(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": pd.Timestamp("2026-07-28T20:00Z")}])
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))

    body = client.get("/analysis/hero?date=2026-07-28&run_id=run-x").json()
    assert body["provenance"]["basis"] == "settled"
    assert body["verdict"] == {
        "magnitude": {"bucket": "under_called", "rungs": 3},
        "regime": None,
        "where": {"bucket": "held"},
        "exceptions": {"bucket": "held"},
    }


def test_hero_soft_fails_when_no_artifact_exists(client, fake_pool):
    fake_pool.cursor.queue([{"h": None}])
    body = client.get("/analysis/hero?date=2026-07-28&run_id=run-x").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing",
                    "run_id": "run-x", "delivery_date": "2026-07-28"}


def test_hero_declares_a_typed_available_or_soft_fail_contract(client):
    schema = client.app.openapi()["paths"]["/analysis/hero"]["get"]["responses"]["200"]
    names = {item["$ref"].rsplit("/", 1)[-1] for item in schema["content"]["application/json"]
             ["schema"]["anyOf"]}
    assert names == {"HeroAvailableResponse", "HeroUnavailableResponse",
                     "HeroUnavailableAtHorizonResponse"}


def test_hero_repeats_byte_identically_for_unchanged_inputs(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": None}])
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": None}])
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))
    first = client.get("/analysis/hero?date=2026-07-28&run_id=run-x")
    second = client.get("/analysis/hero?date=2026-07-28&run_id=run-x")
    assert first.content == second.content


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


def test_path_reconciles_full_terms_to_endpoint_spread(client, fake_pool, monkeypatch):
    artifact = _node_artifact()
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)

    body = client.get("/analysis/path?source=SOURCE&sink=SINK&delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body["available"] is True
    assert body["spread"] == sum(row["contribution"] for row in body["terms"])
    congestion = nodal_congestion(artifact.SF, artifact.E_mu.sum(axis=0))
    assert abs(body["spread"] - (congestion["SINK"] - congestion["SOURCE"])) < 1e-6
    # Full pair: A contributes 4.0, C contributes -13.5, E contributes -0.8.
    assert body["n_terms"] == 3
    assert body["composition"] == {
        "top_share": 13.5 / 18.3,
        "second_share": 4.0 / 18.3,
        "tail_share": 0.8 / 18.3,
        "n_terms": 3,
        "top_constraint_key": "C|D",
        "second_constraint_key": "A|B",
    }


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


def test_node_soft_fails_when_artifact_is_unavailable(client, fake_pool, monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: None)
    body = client.get("/analysis/node?settlement_point=SOURCE&delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing", "run_id": "run-x",
                    "delivery_date": "2026-07-28", "horizon": 1}


def test_settlement_points_returns_the_artifact_vocabulary_not_a_matrix_screen(client, fake_pool, monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _node_artifact())
    body = client.get("/analysis/settlement-points?delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body == {"available": True, "run_id": "run-x", "delivery_date": "2026-07-28",
                    "horizon": 1, "settlement_points": ["SINK", "SOURCE"]}


def test_settlement_points_soft_fails_with_its_declared_model(client, fake_pool, monkeypatch):
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: None)
    body = client.get("/analysis/settlement-points?delivery_date=2026-07-28"
                      "&run_id=run-x&horizon=1").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing", "run_id": "run-x",
                    "delivery_date": "2026-07-28", "horizon": 1}


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
    monkeypatch.setattr(analysis_module, "_grade_constraint_profiles", lambda *_: result)
    monkeypatch.setattr(analysis_module, "_grade_node_profiles", lambda *_: result)

    body = client.get("/analysis/grade?delivery_date=2026-07-28&run_id=run-x").json()

    assert body["available"] is True
    assert body["constraints"] == {
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
    assert body["nodes"] == {
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
    assert "grade" not in body


def test_grade_soft_fails_when_the_served_artifact_horizon_is_missing(client, fake_pool):
    fake_pool.cursor.queue([{"h": None}])

    body = client.get("/analysis/grade?delivery_date=2026-07-28&run_id=run-x").json()

    assert body == {"available": False, "unavailable_reason": "artifact_missing", "run_id": "run-x",
                    "delivery_date": "2026-07-28", "horizon": None}


def test_top_constraints_ranks_the_full_forecast_artifact_and_keeps_settled_missingness(client, fake_pool, monkeypatch):
    hours = pd.date_range("2026-07-28T05:00Z", periods=2, freq="h")
    forecast = pd.DataFrame({"HIGH|BASE": [3.0, 2.0], "LOW|BASE": [0.01, 0.0]}, index=hours)
    settled = pd.DataFrame({"HIGH|BASE": [4.0, 0.0]}, index=hours)
    fake_pool.cursor.queue([{"h": 1}])
    monkeypatch.setattr(analysis_module, "_forecast_mu_profile", lambda *_: forecast)
    monkeypatch.setattr(analysis_module, "_settled_mu_profile", lambda *_: settled)

    body = client.get("/analysis/top-constraints?delivery_date=2026-07-28&run_id=run-x").json()

    assert body == {
        "available": True, "run_id": "run-x", "delivery_date": "2026-07-28", "horizon": 1,
        "n_ranked": 2,
        "rows": [
            {"constraint_key": "HIGH|BASE", "rank": 1, "forecast_total": 5.0,
             "forecast_peak": 3.0, "forecast_hours": 2, "zone": None, "kv_max": None, "settled_rank": 1, "settled_total": 4.0,
             "settled_peak": 4.0, "settled_hours": 1},
            {"constraint_key": "LOW|BASE", "rank": 2, "forecast_total": 0.01,
             "forecast_peak": 0.01, "forecast_hours": 1, "zone": None, "kv_max": None, "settled_rank": None, "settled_total": None,
             "settled_peak": None, "settled_hours": None},
        ],
    }


def test_node_grade_uses_absolute_congestion_so_opposite_sides_cannot_net(monkeypatch):
    hours = pd.RangeIndex(2)
    forecast = pd.DataFrame({"IMPORT": [-1.0, -1.0], "EXPORT": [1.0, 1.0]}, index=hours)
    settled = pd.DataFrame({"IMPORT": [-10.0, -10.0], "EXPORT": [10.0, 10.0]}, index=hours)
    monkeypatch.setattr(analysis_module, "_forecast_node_profile", lambda *_: forecast)
    monkeypatch.setattr(analysis_module, "_settled_node_profile", lambda *_: settled)

    grade = analysis_module._grade_node_profiles(None, "run-x", date(2026, 7, 28), 1)

    assert grade is not None
    assert grade.model.magnitude_overlap == 2 / 11


def test_node_grade_uses_epsilon_only_to_discard_float_residue(monkeypatch):
    hours = pd.RangeIndex(2)
    forecast = pd.DataFrame({"REAL": [0.001, 0.0], "NOISE": [0.0, 0.0]}, index=hours)
    settled = pd.DataFrame({"REAL": [0.001, 0.0], "NOISE": [5e-7, 0.0]}, index=hours)
    monkeypatch.setattr(analysis_module, "_forecast_node_profile", lambda *_: forecast)
    monkeypatch.setattr(analysis_module, "_settled_node_profile", lambda *_: settled)

    grade = analysis_module._grade_node_profiles(None, "run-x", date(2026, 7, 28), 1)

    assert grade is not None
    assert grade.model.detection_ap == 1.0
    assert grade.model.top_decile_daily_capture == 1.0
    assert grade.model.top_decile_hourly_capture == 1.0
    assert grade.model.timing_daily_skill == 1.0


def test_forecast_mu_returns_requested_near_zero_fit_values(client, fake_pool, monkeypatch):
    artifact = SfMuArtifact(
        SF=pd.DataFrame([[1.0], [1.0]], index=["CAST|BASE", "BRUNI_69_1|DFOAVLO5"], columns=["SP"]),
        E_mu=pd.DataFrame(
            [[3.0, 0.03], [2.0, 0.02]],
            index=pd.to_datetime(["2026-07-28T05:00Z", "2026-07-28T06:00Z"]),
            columns=["CAST|BASE", "BRUNI_69_1|DFOAVLO5"],
        ),
    )
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: artifact)
    query = [("delivery_date", "2026-07-28"), ("run_id", "run-x"),
             ("horizon", "1"), ("constraint_key", "CAST|BASE"),
             ("constraint_key", "BRUNI_69_1|DFOAVLO5"), ("constraint_key", "ABSENT|BASE")]

    body = client.get("/analysis/forecast-mu", params=query).json()
    assert [row["constraint_key"] for row in body["rows"]] == ["CAST|BASE", "BRUNI_69_1|DFOAVLO5"]
    assert body["rows"][1] == {
        "constraint_key": "BRUNI_69_1|DFOAVLO5", "mu": [0.03, 0.02], "total": 0.05,
    }
    assert body["missing_constraint_keys"] == ["ABSENT|BASE"]
