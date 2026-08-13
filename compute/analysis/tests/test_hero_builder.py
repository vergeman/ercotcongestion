from datetime import date

import pandas as pd

from compute.analysis import hero_builder
from compute.sf.project import SfMuArtifact


def _artifact():
    return SfMuArtifact(
        SF=pd.DataFrame([[1.0, -1.0], [.5, -.5]], index=["A|B", "C|D"], columns=["N1", "N2"]),
        E_mu=pd.DataFrame([[100.0, 20.0], [80.0, 10.0]], columns=["A|B", "C|D"]),
    )


def test_build_hero_keeps_forecast_on_artifact_keys_and_preserves_all_key_context(monkeypatch):
    D = date(2026, 7, 28)

    def shadow(_conn, _day, *, constraint_keys=None, **_kwargs):
        rows = [
            {"delivery_date": date(2026, 7, 27), "constraint_key": "A|B", "value": 100},
            {"delivery_date": D, "constraint_key": "A|B", "value": 200},
        ]
        return rows if constraint_keys else rows + [
            {"delivery_date": D, "constraint_key": "OUT|SIDE", "value": 500}]

    monkeypatch.setattr(hero_builder, "load_constraint_days", shadow)
    monkeypatch.setattr(hero_builder, "load_load_condition", lambda *_: [
        {"delivery_date": D, "value": 100}])
    monkeypatch.setattr(hero_builder, "load_constraint_geo", lambda *_: [
        {"constraint_key": "A|B", "zone_shares": {"LZ_SOUTH": 1.0},
         "geo_as_of": date(2025, 12, 13)}])
    monkeypatch.setattr(hero_builder, "load_sp_metadata", lambda *_: {
        "N1": {"load_zone": "LZ_SOUTH"}, "N2": {"load_zone": "LZ_NORTH"}})

    slots = hero_builder.build_hero(None, "run", D, 1, "forecast", artifact=_artifact())
    assert slots["magnitude"]["basis"] == "artifact_keys"
    assert slots["magnitude"]["n_keys"] == 2
    assert slots["magnitude"]["value"] == 210.0
    assert slots["magnitude"]["all_keys"]["value"] == 700.0
    assert slots["where"]["zone"] == "south"
    assert slots["where"]["geo_as_of"] == "2025-12-13"
