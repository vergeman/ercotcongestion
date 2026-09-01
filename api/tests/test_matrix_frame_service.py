"""Focused Matrix frame-service tests without FastAPI or cursor fakes."""

from datetime import datetime, timezone

import pandas as pd

from api.services.matrix.frame import build_frame
from api.services.matrix.models import MatrixFrameRequest
from api.services.matrix.repository import MatrixArtifactContext
from compute.projection.codecs import build_sf_mu_artifact, load_sf_mu


T0 = datetime(2026, 7, 1, 5, tzinfo=timezone.utc)


class FakeMatrixData:
    def __init__(self, artifact) -> None:
        self.artifact = artifact
        self.type_requests: list[list[str]] = []

    def artifact_context(self, _delivery_date):
        return MatrixArtifactContext("fc-v1", self.artifact)

    def realized_mu(self, _interval_ts, _constraint_keys):
        return {"BBB|LINE": 9.0}

    def constraint_types(self, keys):
        self.type_requests.append(keys)
        return {"AAA|BASE": "gtc"}


def test_build_frame_assembles_a_frame_from_explicit_collaborators():
    sf = pd.DataFrame({"SP_A": [1.0, 0.5], "SP_B": [0.1, 0.3]}, index=["AAA|BASE", "BBB|LINE"])
    mu = pd.DataFrame({"AAA|BASE": [2.0], "BBB|LINE": [3.0]}, index=pd.to_datetime([T0], utc=True))
    artifact = load_sf_mu(build_sf_mu_artifact(sf, mu))
    repository = FakeMatrixData(artifact)
    request = MatrixFrameRequest(
        interval_ts=T0, row_limit=2, column_limit=2, row_preset="top30",
        constraint_type=None, constraint_search=None, settlement_point_search=None,
        pinned_constraints=[], pinned_settlement_points=[], peek_constraint=None,
        peek_settlement_point=None, column_set="core", orientation="constraints",
        row_order="contribution",
    )

    frame = build_frame(request, repository, {"SP_A": ("hub", "north")})

    assert frame.run_id == "fc-v1"
    assert [row.constraint_key for row in frame.rows] == ["BBB|LINE", "AAA|BASE"]
    assert frame.rows[0].ercot_dam_mu == 9.0
    assert frame.columns[0].settlement_point_type == "hub"
    assert repository.type_requests == [["BBB|LINE", "AAA|BASE"]]
