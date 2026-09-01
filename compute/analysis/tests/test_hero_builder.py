from datetime import date

import pandas as pd

from compute.analysis import hero_builder
from compute.projection.codecs import SfMuArtifact


def _artifact():
    return SfMuArtifact(
        SF=pd.DataFrame([[1.0, -1.0], [.5, -.5]], index=["A|B", "C|D"], columns=["N1", "N2"]),
        E_mu=pd.DataFrame([[100.0, 20.0], [80.0, 10.0]],
                          index=pd.to_datetime(["2026-07-28T20:00Z", "2026-07-28T21:00Z"]),
                          columns=["A|B", "C|D"]),
    )


def test_build_hero_keeps_forecast_on_artifact_keys_and_preserves_all_key_context(monkeypatch):
    D = date(2026, 7, 28)

    def shadow(_conn, _day, *, constraint_keys=None, ct_hours=None, **_kwargs):
        rows = [
            {"delivery_date": date(2026, 7, 27), "constraint_key": "A|B", "value": 100},
            {"delivery_date": D, "constraint_key": "A|B", "value": 200},
        ]
        if ct_hours:
            return rows
        return rows if constraint_keys else rows + [
            {"delivery_date": D, "constraint_key": "OUT|SIDE", "value": 500}]

    monkeypatch.setattr(hero_builder, "load_constraint_days", shadow)
    monkeypatch.setattr(hero_builder, "load_forecast_constraint_days", lambda *_args, **_kwargs: [
        {"delivery_date": date(2026, 7, 27), "constraint_key": "A|B", "value": 120},
        {"delivery_date": D, "constraint_key": "A|B", "value": 210},
    ])
    monkeypatch.setattr(hero_builder, "load_load_condition", lambda *_: [
        {"delivery_date": D, "value": 100}])
    monkeypatch.setattr(hero_builder, "load_constraint_geo", lambda *_: [
        {"constraint_key": "A|B", "zone_shares": {"LZ_SOUTH": 1.0},
         "geo_as_of": date(2025, 12, 13)}])
    monkeypatch.setattr(hero_builder, "load_sp_metadata", lambda *_: {
        "N1": {"load_zone": "LZ_SOUTH"}, "N2": {"load_zone": "LZ_NORTH"}})

    slots = hero_builder.build_hero(None, "run", D, 1, "forecast", artifact=_artifact()).slots
    assert slots["magnitude"]["basis"] == "forecast_history_artifact_keys"
    assert slots["magnitude"]["n_keys"] == 2
    assert slots["magnitude"]["value"] == 210.0
    assert slots["magnitude"]["all_keys"]["value"] == 700.0
    assert slots["magnitude"]["high_congestion_hours"]["value"] == 210.0
    assert slots["magnitude"]["high_congestion_hours"]["hours_ct"] == [15, 16, 17, 18]
    assert slots["where"]["zone"] == "south"
    # N1 (LZ_SOUTH) carries -(SF.T @ Σμ) = -195 → the leading zone reads negative.
    assert slots["where"]["zone_congestion"] == -195.0
    assert slots["where"]["geo_as_of"] == "2025-12-13"
    assert slots["exceptions"] == {"available": False, "bucket": "unavailable"}


def test_benchmark_split_uses_direct_load_zone_spps_before_hubs():
    artifact = SfMuArtifact(
        SF=pd.DataFrame([[1.0, -1.0]], index=["A|B"],
                        columns=["LZ_NORTH", "LZ_SOUTH"]),
        E_mu=pd.DataFrame(
            [[1.0], [1.0], [10.0], [8.0]],
            index=pd.to_datetime([
                "2026-07-28T14:00Z", "2026-07-28T15:00Z",
                "2026-07-28T20:00Z", "2026-07-28T21:00Z",
            ]),
            columns=["A|B"],
        ),
    )

    assert hero_builder._benchmark_split(artifact) == {
        "family": "load zones",
        "positive": "LZ_SOUTH",
        "negative": "LZ_NORTH",
        "positive_label": "South LZ",
        "negative_label": "North LZ",
        "positive_value": 9.0,
        "negative_value": -9.0,
        "spread": 18.0,
    }


def test_build_hero_reports_unmodeled_dam_constraint_tiers(monkeypatch):
    D = date(2026, 7, 28)

    def shadow(_conn, _day, *, constraint_keys=None, ct_hours=None, **_kwargs):
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

    slot = hero_builder.build_hero(None, "run", D, 1, "settled", artifact=_artifact()).slots["exceptions"]
    assert slot["bucket"] == "one_or_two"
    assert slot["tier_0"] == [{"constraint_key": "NEW|ONE", "value": 30.0, "rank": 1, "n": 31}]
    assert [item["constraint_key"] for item in slot["tier_1"]] == ["NEW|ONE", "TOP|TWO"]
    assert [item["rank"] for item in slot["tier_1"]] == [1, 2]


def test_settled_build_hero_loads_shared_inputs_once(monkeypatch):
    D = date(2026, 7, 28)
    calls = {"constraints": 0, "forecast": 0, "geo": 0, "metadata": 0, "condition": 0}

    def constraints(_conn, _day, *, constraint_keys=None, **_kwargs):
        calls["constraints"] += 1
        return [{"delivery_date": D, "constraint_key": "A|B", "value": 10}]

    def forecast(*_args, **_kwargs):
        calls["forecast"] += 1
        return [{"delivery_date": D, "constraint_key": "A|B", "value": 10}]

    def geo(*_args):
        calls["geo"] += 1
        return []

    def metadata(*_args):
        calls["metadata"] += 1
        return {}

    def condition(*_args):
        calls["condition"] += 1
        return {"series": "load.system", "pct": 0.0}

    monkeypatch.setattr(hero_builder, "load_constraint_days", constraints)
    monkeypatch.setattr(hero_builder, "load_forecast_constraint_days", forecast)
    monkeypatch.setattr(hero_builder, "load_constraint_geo", geo)
    monkeypatch.setattr(hero_builder, "load_sp_metadata", metadata)
    monkeypatch.setattr(hero_builder, "build_hero_condition", condition)

    built = hero_builder.build_hero(
        None, "run", D, 1, "settled", artifact=_artifact(),
        include_forecast_comparison=True,
    )

    assert calls == {"constraints": 3, "forecast": 1, "geo": 1, "metadata": 1, "condition": 1}
    assert built.slots["magnitude"]["basis"] == "artifact_keys"
    assert built.forecast_slots is not None
    assert built.forecast_slots["magnitude"]["basis"] == "forecast_history_artifact_keys"
