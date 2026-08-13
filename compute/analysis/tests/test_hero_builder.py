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
    assert slots["exceptions"] == {"available": False, "bucket": "unavailable"}


def test_build_hero_reports_unmodeled_dam_constraint_tiers(monkeypatch):
    D = date(2026, 7, 28)

    def shadow(_conn, _day, *, constraint_keys=None, **_kwargs):
        artifact_rows = [{"delivery_date": D, "constraint_key": "A|B", "value": 10}]
        all_rows = artifact_rows + [
            {"delivery_date": D, "constraint_key": "NEW|ONE", "value": 30},
            {"delivery_date": D, "constraint_key": "TOP|TWO", "value": 20},
            {"delivery_date": date(2026, 7, 27), "constraint_key": "TOP|TWO", "value": 25},
            {"delivery_date": date(2026, 7, 26), "constraint_key": "TOP|TWO", "value": 10},
            {"delivery_date": D, "constraint_key": "LOW|RANK", "value": 5},
            {"delivery_date": date(2026, 7, 27), "constraint_key": "LOW|RANK", "value": 9},
            {"delivery_date": date(2026, 7, 26), "constraint_key": "LOW|RANK", "value": 8},
            {"delivery_date": date(2026, 7, 25), "constraint_key": "LOW|RANK", "value": 7},
        ]
        return artifact_rows if constraint_keys else all_rows

    monkeypatch.setattr(hero_builder, "load_constraint_days", shadow)
    monkeypatch.setattr(hero_builder, "load_load_condition", lambda *_: [{"delivery_date": D, "value": 100}])
    monkeypatch.setattr(hero_builder, "load_constraint_geo", lambda *_: [])
    monkeypatch.setattr(hero_builder, "load_sp_metadata", lambda *_: {})

    slot = hero_builder.build_hero(None, "run", D, 1, "settled", artifact=_artifact())["exceptions"]
    assert slot["bucket"] == "one_or_two"
    assert slot["tier_0"] == [{"constraint_key": "NEW|ONE", "value": 30.0, "rank": 1, "n": 31}]
    assert [item["constraint_key"] for item in slot["tier_1"]] == ["NEW|ONE", "TOP|TWO"]
    assert [item["rank"] for item in slot["tier_1"]] == [1, 2]
