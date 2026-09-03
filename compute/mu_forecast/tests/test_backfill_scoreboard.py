"""Scoreboard persistence accepts computed μ evaluation rows."""
from __future__ import annotations

import pandas as pd
import pytest

from compute.jobs.backfill_scoreboard import build_rows


def test_backfill_maps_only_admitted_compute_sources():
    score = pd.DataFrame([{
        "week": "2026-07-01T00:00:00Z",
        "source": "compute_mu_model_walk_forward",
        "rank_spearman": 0.5, "sign_agree": 0.6, "topdecile_hit": 0.7,
        "sf_coverage": 1.0, "model_coverage": 0.9, "n_hours": 168, "n_nodes": 100,
    }])
    assert build_rows(score, run_id="run-x")[0][2] == "scoreboard_model_backtest_nodal"

    score = pd.DataFrame([{"week": "2026-07-01T00:00:00Z", "source": "model"}])
    with pytest.raises(ValueError, match="unadmitted"):
        build_rows(score, run_id="run-x")
