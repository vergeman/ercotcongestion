"""Run-artifact path convention for backfill_scoreboard (plan/0113).

`--run-id` defaults the score CSV to the run's μ-stage `mu/mu_score_weekly.csv`.
"""
from __future__ import annotations

from compute.jobs.backfill_nodal import scores_path_for
import pandas as pd
import pytest

from compute.jobs.backfill_scoreboard import build_rows, resolve_board_paths


def test_run_id_defaults_score_under_mu():
    score = resolve_board_paths("mu-all-v1", None)
    assert score == scores_path_for("mu-all-v1")
    assert score.endswith("runs/mu-all-v1/mu/mu_score_weekly.csv")


def test_explicit_score_overrides_the_default():
    assert resolve_board_paths("mu-all-v1", "/s.csv") == "/s.csv"


def test_backfill_maps_only_admitted_compute_comparisons(tmp_path):
    path = tmp_path / "scores.csv"
    pd.DataFrame([{
        "week": "2026-07-01T00:00:00Z",
        "source": "compute_mu_model_walk_forward",
        "rank_spearman": 0.5, "sign_agree": 0.6, "topdecile_hit": 0.7,
        "sf_coverage": 1.0, "model_coverage": 0.9, "n_hours": 168, "n_nodes": 100,
    }]).to_csv(path, index=False)
    assert build_rows(str(path), run_id="run-x")[0][2] == "scoreboard_model_backtest_nodal"

    pd.DataFrame([{"week": "2026-07-01T00:00:00Z", "source": "model"}]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="unadmitted"):
        build_rows(str(path), run_id="run-x")
