"""Run-artifact path convention for backfill_scoreboard (plan/0113).

`--run-id` defaults the score CSV to the run's μ-stage `mu/mu_score_weekly.csv`.
"""
from __future__ import annotations

from compute.jobs.backfill_nodal import scores_path_for
from compute.jobs.backfill_scoreboard import resolve_board_paths


def test_run_id_defaults_score_under_mu():
    score = resolve_board_paths("mu-all-v1", None)
    assert score == scores_path_for("mu-all-v1")
    assert score.endswith("runs/mu-all-v1/mu/mu_score_weekly.csv")


def test_explicit_score_overrides_the_default():
    assert resolve_board_paths("mu-all-v1", "/s.csv") == "/s.csv"
