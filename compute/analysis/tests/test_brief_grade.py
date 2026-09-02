"""Boundary tests for the compute-owned Brief grade implementation."""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd

from compute.analysis.brief_grade import SOURCE_DEFINITIONS, serialize_grade_half
from compute.analysis.grade import GradeMetrics, GradeResult
from compute.jobs import daily_forecast
from compute.jobs import materialize_brief_grade


def test_compute_brief_grade_modules_do_not_import_the_api_application():
    assert "api.analysis" not in sys.modules
    assert materialize_brief_grade.grade_constraint_profiles.__module__ == "compute.analysis.brief_grade"


def test_serialize_grade_half_is_neutral_data_not_an_api_response_model():
    metrics = GradeMetrics(0.62, 0.50, 0.55, 0.34)

    result = serialize_grade_half(GradeResult(("A|B", "C|D"), metrics, metrics))

    assert {key: result[key] for key in ("graded", "universe_size", "support")} == {
        "graded": True,
        "universe_size": 2,
        "support": None,
    }
    assert [item["id"] for item in result["sources"]] == [
        "brief_model_artifact_profile", "brief_persistence_prior_settled_profile",
    ]
    assert [item["id"] for item in result["source_metrics"]] == [
        "brief_model_artifact_profile", "brief_persistence_prior_settled_profile",
    ]
    assert "model" not in result


def test_materializer_preserves_the_fixed_grade_fixture(monkeypatch):
    metrics = GradeMetrics(0.62, 0.50, 0.55, 0.34)
    result = GradeResult(("A|B", "C|D"), metrics, metrics)
    monkeypatch.setattr(materialize_brief_grade, "grade_constraint_profiles", lambda *_: result)
    monkeypatch.setattr(materialize_brief_grade, "grade_node_profiles", lambda *_: result)

    class Cursor:
        def __init__(self):
            self.writes = []

        def execute(self, sql, params):
            self.writes.append((sql, params))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Conn:
        def __init__(self):
            self.cursor_ = Cursor()
            self.commits = 0

        def cursor(self, **_):
            return self.cursor_

        def commit(self):
            self.commits += 1

    conn = Conn()

    assert materialize_brief_grade.materialize_day(conn, "run-x", date(2026, 7, 28), 1)
    assert conn.commits == 1
    assert [params[3] for _, params in conn.cursor_.writes] == ["constraints", "nodes"]
    expected = {
        "graded": True,
        "universe_size": 2,
        "support": None,
    }
    assert all({key: params[-1].obj[key] for key in expected} == expected
               for _, params in conn.cursor_.writes)
    assert all(params[-1].obj["source_metrics"][0]["id"] == "brief_model_artifact_profile"
               for _, params in conn.cursor_.writes)


def test_brief_source_labels_are_the_display_contract():
    assert {source.id: source.label for source in SOURCE_DEFINITIONS} == {
        "brief_model_artifact_profile": "Artifact profile forecast",
        "brief_persistence_prior_settled_profile": "Prior-settled profile persistence",
        "brief_climatology_trailing_settled_profile": "Trailing-window Average (Baseline)",
    }


def test_brief_materialization_failure_remains_non_fatal_after_publish(monkeypatch):
    conn = type("Conn", (), {"commits": 0, "rollbacks": 0})()
    conn.commit = lambda: setattr(conn, "commits", conn.commits + 1)
    conn.rollback = lambda: setattr(conn, "rollbacks", conn.rollbacks + 1)
    graded_day = pd.Timestamp("2026-07-28", tz="UTC")
    monkeypatch.setattr(daily_forecast, "resolve_gradeable_date", lambda *_: graded_day)
    monkeypatch.setattr(daily_forecast, "grade_day", lambda *_ , **__: [])
    monkeypatch.setattr(daily_forecast, "persist_grades", lambda *_: 2)
    monkeypatch.setattr(daily_forecast, "materialize_brief_grade",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("brief unavailable")))

    assert daily_forecast._grade_latest(conn, "run-x") is None
    assert conn.commits == 1
    assert conn.rollbacks == 1
