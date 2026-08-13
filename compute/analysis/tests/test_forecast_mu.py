import pandas as pd

from compute.analysis.forecast_mu import forecast_mu_rows
from compute.sf.project import SfMuArtifact


def test_forecast_mu_rows_keeps_near_zero_fit_values_only_when_requested():
    artifact = SfMuArtifact(
        SF=pd.DataFrame([[1.0], [1.0]], index=["CAST|BASE", "LOW|BASE"], columns=["SP"]),
        E_mu=pd.DataFrame([[2.0, 0.01], [3.0, 0.02]], columns=["CAST|BASE", "LOW|BASE"]),
    )
    assert list(forecast_mu_rows(artifact, ["CAST|BASE", "LOW|BASE"]).columns) == ["CAST|BASE"]
    result = forecast_mu_rows(artifact, ["CAST|BASE", "LOW|BASE", "UNKNOWN|BASE"],
                              include_below_floor=True)
    assert list(result.columns) == ["CAST|BASE", "LOW|BASE"]
    assert result["LOW|BASE"].tolist() == [0.01, 0.02]
