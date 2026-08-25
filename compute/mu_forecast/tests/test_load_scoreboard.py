"""Run-artifact path convention for load_scoreboard (plan/0113).

`--run-id` defaults the score CSV to the run's μ-stage `mu/mu_score_weekly.csv`
(the score schema, NOT `mu_model`'s `mu_weekly.csv` calibration output) and the
bands CSV to the forecast-stage `forecast/mu_bands_weekly.csv`; explicit `--score`
/ `--bands` always win.
"""
from __future__ import annotations

from compute.jobs.backfill_nodal import bands_path_for, scores_path_for
from compute.jobs.load_scoreboard import resolve_board_paths


def test_run_id_defaults_score_under_mu_and_bands_under_forecast():
    score, bands = resolve_board_paths("mu-all-v1", None, None)
    assert score == scores_path_for("mu-all-v1")
    assert bands == bands_path_for("mu-all-v1")
    assert score.endswith("runs/mu-all-v1/mu/mu_score_weekly.csv")
    assert bands.endswith("runs/mu-all-v1/forecast/mu_bands_weekly.csv")


def test_explicit_paths_override_each_default_independently():
    assert resolve_board_paths("mu-all-v1", "/s.csv", "/b.csv") == (
        "/s.csv", "/b.csv")
    # one override, the other still derived
    score, bands = resolve_board_paths("mu-all-v1", "/s.csv", None)
    assert score == "/s.csv"
    assert bands == bands_path_for("mu-all-v1")
