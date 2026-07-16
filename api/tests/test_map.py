"""Tests for the /map/* endpoints (plan/0090 0004).

Two layers:

* **Unit** (fake_pool) — wiring, response shape, the §6 identifiability
  headline (`node_max_abs_sf` + window confidence on signed rows),
  per-request run/window resolution, and the 503 soft-fail. Rows are queued
  in the exact order each endpoint's queries fire (the fake cursor is FIFO).
* **Integration** (`@pytest.mark.integration`, RUN_INTEGRATION=1) — hits the
  real map-v1 DB to prove the exposure/reach **transpose** (spec §7) and that
  `/map/meta` reports the configured run with a real current window.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import map as map_module

WS = datetime(2025, 11, 4, tzinfo=timezone.utc)
WE = datetime(2026, 7, 2, tzinfo=timezone.utc)


@pytest.fixture
def configured_run(monkeypatch):
    """Pin the resolved run so _resolve does a single max(window_start) query."""
    monkeypatch.setattr(map_module, "MAP_RUN_ID", "map-v1")


def _meta_row(**over) -> dict:
    row = {
        "run_id": "map-v1",
        "window_start": WS,
        "window_end": WE,
        "fit_r2": 0.81,
        "oos_r2": 0.62,
        "coverage": 0.94,
        "sf_stability": 0.47,
        "n_kept": 120,
    }
    row.update(over)
    return row


# ---- /map/meta -----------------------------------------------------------

def test_meta_returns_current_window(client, fake_pool, configured_run):
    fake_pool.cursor.queue([{"ws": WS}])       # _resolve → max(window_start)
    fake_pool.cursor.queue([_meta_row()])      # _meta_row

    r = client.get("/map/meta")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "map-v1"
    assert body["window_start"].startswith("2025-11-04")
    assert body["fit_r2"] == 0.81
    assert body["oos_r2"] == 0.62 and body["coverage"] == 0.94
    assert body["sf_stability"] == 0.47


def test_meta_503_when_no_window_built(client, fake_pool, configured_run):
    fake_pool.cursor.queue([])  # max(window_start) → None
    r = client.get("/map/meta")
    assert r.status_code == 503


def test_resolution_defaults_to_newest_run(client, fake_pool, monkeypatch):
    """MAP_RUN_ID None → resolve newest run_id from sf_window_meta."""
    monkeypatch.setattr(map_module, "MAP_RUN_ID", None)
    fake_pool.cursor.queue([{"run_id": "map-v1"}])  # newest run
    fake_pool.cursor.queue([{"ws": WS}])            # its max window_start
    fake_pool.cursor.queue([_meta_row()])

    r = client.get("/map/meta")
    assert r.status_code == 200
    assert r.json()["run_id"] == "map-v1"


# ---- /map/constraints ----------------------------------------------------

def test_constraints_overlay_shape(client, fake_pool, configured_run):
    fake_pool.cursor.queue([{"ws": WS}])
    fake_pool.cursor.queue([{
        "constraint_key": "CONSTR_A",
        "lat": 31.9, "lon": -102.1,
        "zone_shares": {"west": 0.8, "north": 0.2},
        "kv_mean": 345.0, "kv_max": 345.0,
        "spread_km": 40.0, "max_abs_sf": 0.55, "binding_hours": 120,
    }])

    r = client.get("/map/constraints")
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["constraint_key"] == "CONSTR_A"
    assert rows[0]["zone_shares"] == {"west": 0.8, "north": 0.2}
    assert rows[0]["max_abs_sf"] == 0.55


# ---- /map/exposures ------------------------------------------------------

def test_exposures_headline_and_confidence(client, fake_pool, configured_run):
    fake_pool.cursor.queue([{"ws": WS}])            # _resolve
    fake_pool.cursor.queue([_meta_row()])           # _meta_row (confidence)
    fake_pool.cursor.queue([{"m": 0.72}])           # node_max_abs_sf
    fake_pool.cursor.queue([                         # top-k exposures
        {"constraint_key": "CONSTR_A", "sf": 0.72, "lat": 31.9, "lon": -102.1,
         "max_abs_sf": 0.72, "binding_hours": 120},
        {"constraint_key": "CONSTR_B", "sf": -0.31, "lat": 32.0, "lon": -97.0,
         "max_abs_sf": 0.40, "binding_hours": 55},
    ])

    r = client.get("/map/exposures", params={"sp": "LZ_WEST", "k": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sp"] == "LZ_WEST" and body["k"] == 5
    # §6: unsigned headline + window confidence ship alongside the signed rows.
    assert body["node_max_abs_sf"] == 0.72
    assert body["oos_r2"] == 0.62 and body["sf_stability"] == 0.47
    assert [e["constraint_key"] for e in body["exposures"]] == ["CONSTR_A", "CONSTR_B"]
    assert body["exposures"][1]["sf"] == -0.31


# ---- /map/reach ----------------------------------------------------------

def test_reach_signed_with_coords(client, fake_pool, configured_run, monkeypatch):
    monkeypatch.setattr(map_module, "_SP_COORDS",
                        {"LZ_WEST": (31.9, -102.1), "LZ_NORTH": (33.0, -97.0)})
    fake_pool.cursor.queue([{"ws": WS}])                             # _resolve
    fake_pool.cursor.queue([_meta_row()])                            # _meta_row
    fake_pool.cursor.queue([{"lat": 31.5, "lon": -101.0,             # constraint geo
                             "max_abs_sf": 0.72}])
    fake_pool.cursor.queue([                                          # top-k reach
        {"settlement_point": "LZ_WEST", "sf": 0.72},
        {"settlement_point": "LZ_NORTH", "sf": -0.30},
    ])

    r = client.get("/map/reach", params={"constraint": "CONSTR_A", "k": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["constraint_key"] == "CONSTR_A"
    assert body["lat"] == 31.5 and body["max_abs_sf"] == 0.72
    assert body["oos_r2"] == 0.62
    sps = body["sps"]
    assert sps[0] == {"settlement_point": "LZ_WEST", "sf": 0.72, "lat": 31.9, "lon": -102.1}
    assert sps[1]["sf"] == -0.30 and sps[1]["lat"] == 33.0  # opposite sign end


# ---- Integration: transpose + real run resolution ------------------------

@pytest.mark.integration
def test_meta_reports_configured_run(real_client):
    r = real_client.get("/map/meta")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "map-v1"
    assert body["fit_r2"] is not None
    # backfilled by compute.sf.eval (0003 Commit D)
    assert body["oos_r2"] is not None
    assert body["coverage"] is not None
    assert body["sf_stability"] is not None


@pytest.mark.integration
def test_exposure_reach_transpose(real_client):
    """spec §7: X in /map/reach?constraint=c ⇔ c in /map/exposures?sp=X, same sf."""
    constraints = real_client.get("/map/constraints").json()
    assert constraints, "no constraints served for map-v1"
    c = constraints[0]["constraint_key"]

    reach = real_client.get("/map/reach", params={"constraint": c, "k": 5}).json()
    assert reach["sps"], f"constraint {c} drives no nodes"
    top = reach["sps"][0]
    sp, sf_reach = top["settlement_point"], top["sf"]

    # k large enough that c is in sp's full exposure list.
    exposures = real_client.get(
        "/map/exposures", params={"sp": sp, "k": 500}).json()["exposures"]
    match = [e for e in exposures if e["constraint_key"] == c]
    assert match, f"{c} missing from /map/exposures?sp={sp}"
    assert match[0]["sf"] == pytest.approx(sf_reach), "transpose sf mismatch"
