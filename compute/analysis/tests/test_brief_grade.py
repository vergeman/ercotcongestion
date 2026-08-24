"""Boundary tests for the compute-owned Brief grade implementation."""
from __future__ import annotations

import sys

from compute.analysis.brief_grade import serialize_grade_half
from compute.analysis.grade import GradeMetrics, GradeResult
from compute.jobs import materialize_brief_grade


def test_compute_brief_grade_modules_do_not_import_the_api_application():
    assert "api.analysis" not in sys.modules
    assert materialize_brief_grade.grade_constraint_profiles.__module__ == "compute.analysis.brief_grade"


def test_serialize_grade_half_is_neutral_data_not_an_api_response_model():
    metrics = GradeMetrics(0.62, 0.50, 0.55, 0.34)

    result = serialize_grade_half(GradeResult(("A|B", "C|D"), metrics, metrics))

    assert result == {
        "graded": True,
        "universe_size": 2,
        "model": metrics.__dict__,
        "persistence": metrics.__dict__,
        "climatology": None,
        "support": None,
    }
