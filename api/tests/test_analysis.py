from datetime import date

import pandas as pd

import analysis as analysis_module
from compute.sf.project import SfMuArtifact


def _artifact():
    return SfMuArtifact(
        SF=pd.DataFrame([[1.0]], index=["A|B"], columns=["SP"]),
        E_mu=pd.DataFrame([[4.0], [9.0]], index=pd.to_datetime([
            "2026-07-28T05:00Z", "2026-07-28T06:00Z"]), columns=["A|B"]),
    )


def _slots(basis):
    return {
        "magnitude": {"bucket": "near_top" if basis == "settled" else "ordinary"},
        "regime": {"bucket": "load_record_high"},
        "where": {"bucket": "concentrated", "zone": "south"},
        "exceptions": {"bucket": "none"},
    }


def test_hero_resolves_served_horizon_and_returns_forecast_segments(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"h": 1}])            # horizon resolve
    fake_pool.cursor.queue([{"ts": None}])        # DAM coverage
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))

    response = client.get("/analysis/hero?date=2026-07-28&run_id=run-x")
    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == {"run_id": "run-x", "delivery_date": "2026-07-28",
                                  "horizon": 1, "basis": "forecast"}
    assert body["verdict"] is None
    assert body["cursor"] == {"ws": "2026-07-28T05:00:00Z", "we": "2026-07-29T05:00:00Z",
                              "t": "2026-07-28T06:00:00Z"}
    assert all(part["ref"] in body["slots"] for group in body["segments"].values() for part in group)


def test_hero_settled_phase_grades_each_reconcilable_slot_independently(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": pd.Timestamp("2026-07-28T20:00Z")}])
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))

    body = client.get("/analysis/hero?date=2026-07-28&run_id=run-x").json()
    assert body["provenance"]["basis"] == "settled"
    assert body["verdict"] == {
        "magnitude": {"bucket": "under_called", "rungs": 2},
        "regime": None,
        "where": {"bucket": "held"},
        "exceptions": {"bucket": "held"},
    }


def test_hero_soft_fails_when_no_artifact_exists(client, fake_pool):
    fake_pool.cursor.queue([{"h": None}])
    body = client.get("/analysis/hero?date=2026-07-28&run_id=run-x").json()
    assert body == {"available": False, "unavailable_reason": "artifact_missing",
                    "run_id": "run-x", "delivery_date": "2026-07-28"}


def test_hero_declares_a_typed_available_or_soft_fail_contract(client):
    schema = client.app.openapi()["paths"]["/analysis/hero"]["get"]["responses"]["200"]
    names = {item["$ref"].rsplit("/", 1)[-1] for item in schema["content"]["application/json"]
             ["schema"]["anyOf"]}
    assert names == {"HeroAvailableResponse", "HeroUnavailableResponse",
                     "HeroUnavailableAtHorizonResponse"}


def test_hero_repeats_byte_identically_for_unchanged_inputs(client, fake_pool, monkeypatch):
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": None}])
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"ts": None}])
    monkeypatch.setattr(analysis_module, "load_daily_artifact", lambda *_: _artifact())
    monkeypatch.setattr(analysis_module, "build_hero", lambda *_a, **_k: _slots(_a[-1]))
    first = client.get("/analysis/hero?date=2026-07-28&run_id=run-x")
    second = client.get("/analysis/hero?date=2026-07-28&run_id=run-x")
    assert first.content == second.content
