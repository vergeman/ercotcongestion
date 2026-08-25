from pathlib import Path

import pytest

from compute.artifacts import RunArtifacts
from compute.jobs import backfill_nodal, daily_forecast
from compute.mu_forecast.model import runner as mu_model


@pytest.mark.parametrize("run_id", ["mu-all-v1", "2026-08-22", "nested/run"])
@pytest.mark.parametrize("root", [Path("runs"), Path("/tmp/runs")])
def test_run_artifacts_use_the_canonical_mu_and_forecast_layout(run_id, root):
    artifacts = RunArtifacts(run_id, root)

    assert artifacts.weekly_metrics == root / run_id / "mu" / "mu_weekly.csv"
    assert artifacts.predictions == root / run_id / "mu" / "mu_preds.npz"
    assert artifacts.scores == root / run_id / "mu" / "mu_score_weekly.csv"
    assert artifacts.bands == root / run_id / "forecast" / "mu_bands_weekly.csv"
    assert artifacts.nodal_panel == root / run_id / "forecast" / "mu_nodal.npz"


@pytest.mark.parametrize("run_id", ["mu-all-v1", "2026-08-22"])
def test_path_wrappers_delegate_to_run_artifacts(run_id, tmp_path, monkeypatch):
    root = tmp_path / "runs"
    artifacts = RunArtifacts(run_id, root)
    for module in (mu_model, daily_forecast, backfill_nodal):
        monkeypatch.setattr(module, "RUNS_ROOT", root)

    assert mu_model.weekly_path_for(run_id) == str(artifacts.weekly_metrics)
    assert mu_model.preds_path_for(run_id) == str(artifacts.predictions)
    assert daily_forecast.preds_path_for(run_id) == str(artifacts.predictions)
    assert backfill_nodal.preds_path_for(run_id) == str(artifacts.predictions)
    assert backfill_nodal.scores_path_for(run_id) == str(artifacts.scores)
    assert backfill_nodal.bands_path_for(run_id) == str(artifacts.bands)
    assert backfill_nodal.nodal_path_for(run_id) == str(artifacts.nodal_panel)
