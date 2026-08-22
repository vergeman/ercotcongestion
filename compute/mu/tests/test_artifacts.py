from pathlib import Path

import pytest

from compute.artifacts import RunArtifacts


@pytest.mark.parametrize("run_id", ["mu-all-v1", "2026-08-22", "nested/run"])
@pytest.mark.parametrize("root", [Path("runs"), Path("/tmp/runs")])
def test_run_artifacts_use_the_canonical_mu_and_forecast_layout(run_id, root):
    artifacts = RunArtifacts(run_id, root)

    assert artifacts.weekly_metrics == root / run_id / "mu" / "mu_weekly.csv"
    assert artifacts.predictions == root / run_id / "mu" / "mu_preds.npz"
    assert artifacts.scores == root / run_id / "mu" / "mu_score_weekly.csv"
    assert artifacts.bands == root / run_id / "forecast" / "mu_bands_weekly.csv"
    assert artifacts.nodal_panel == root / run_id / "forecast" / "mu_nodal.npz"
