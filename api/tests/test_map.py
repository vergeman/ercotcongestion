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


# ---- /map/overview -------------------------------------------------------

def test_overview_cores_types_and_grouping(client, fake_pool, configured_run,
                                           monkeypatch):
    """The bulk overview: each constraint at its core, typed, with its signed
    top-k node field grouped from the single ANY(keys) node query, and the
    per-constraint min_frac floor dropping the noise-floor node."""
    monkeypatch.setattr(map_module, "_SP_COORDS",
                        {"N1": (29.7, -95.3), "N2": (32.6, -101.0),
                         "N3": (30.0, -99.0), "N4": (33.0, -97.0)})
    fake_pool.cursor.queue([{"ws": WS}])            # _resolve
    fake_pool.cursor.queue([_meta_row()])           # _meta_row
    fake_pool.cursor.queue([                         # top-n constraint_geo rows
        {"constraint_key": "AAA|BASE CASE", "ctype": "gtc", "binding_hours": 300,
         "max_abs_sf": 0.50, "core_lat": 29.7, "core_lon": -95.3,
         "lat": 31.3, "lon": -99.8},               # core != centroid (de-piled)
        {"constraint_key": "BBB|LINE", "ctype": "transmission", "binding_hours": 200,
         "max_abs_sf": 0.40, "core_lat": 32.6, "core_lon": -101.0,
         "lat": 31.0, "lon": -99.0},
    ])
    fake_pool.cursor.queue([                         # ANY(keys) nodes, key then |sf|
        {"constraint_key": "AAA|BASE CASE", "settlement_point": "N1", "sf": 0.50},
        {"constraint_key": "AAA|BASE CASE", "settlement_point": "N2", "sf": -0.40},
        {"constraint_key": "AAA|BASE CASE", "settlement_point": "N3", "sf": 0.02},  # < 0.15*0.50, dropped
        {"constraint_key": "BBB|LINE", "settlement_point": "N4", "sf": 0.40},
    ])

    r = client.get("/map/overview", params={"n": 70, "k": 16})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "map-v1" and body["n"] == 70
    assert body["oos_r2"] == 0.62 and body["sf_stability"] == 0.47

    a, b = body["constraints"]
    assert a["constraint_key"] == "AAA|BASE CASE" and a["ctype"] == "gtc"
    # positioned at the core, not the |SF|-mean centroid
    assert a["core_lat"] == 29.7 and a["lat"] == 31.3
    # the noise-floor node (0.02 < 0.15*0.50) is dropped; the two real ones stay
    assert [n["settlement_point"] for n in a["nodes"]] == ["N1", "N2"]
    assert a["nodes"][1]["sf"] == -0.40 and a["nodes"][1]["lat"] == 32.6  # opposite end, coord joined
    assert b["ctype"] == "transmission" and [n["settlement_point"] for n in b["nodes"]] == ["N4"]


def test_overview_truncates_to_k_nodes(client, fake_pool, configured_run, monkeypatch):
    """k caps the per-constraint field even when more nodes clear the floor."""
    monkeypatch.setattr(map_module, "_SP_COORDS", {})
    fake_pool.cursor.queue([{"ws": WS}])
    fake_pool.cursor.queue([_meta_row()])
    fake_pool.cursor.queue([{
        "constraint_key": "AAA|c", "ctype": "transmission", "binding_hours": 100,
        "max_abs_sf": 1.0, "core_lat": 30.0, "core_lon": -99.0,
        "lat": 30.0, "lon": -99.0,
    }])
    fake_pool.cursor.queue([
        {"constraint_key": "AAA|c", "settlement_point": f"N{i}", "sf": 1.0 - 0.01 * i}
        for i in range(5)
    ])

    body = client.get("/map/overview", params={"n": 1, "k": 2}).json()
    assert [n["settlement_point"] for n in body["constraints"][0]["nodes"]] == ["N0", "N1"]


# ---- /map/constraints/ranked ---------------------------------------------

def _ranked_blob():
    """A two-constraint SF+E_mu artifact for the ranked-endpoint unit tests.

    AAA outranks BBB: AAA has heavier E_mu (mass 20 vs 2) and wider reach
    (Σ|SF| 1.41 vs 0.70) → contribution 28.2 vs 1.40. AAA's dipole is N1 sink
    (+0.8) vs N2 source (−0.6); N3 (+0.01) sits below the 0.05·peak floor.
    """
    import pandas as pd
    from compute.sf.project import build_sf_mu_artifact

    SF = pd.DataFrame(
        {"N1": [0.8, 0.2], "N2": [-0.6, 0.0], "N3": [0.01, 0.5]},
        index=["AAA|BASE", "BBB|LINE"],
    )
    hours = pd.to_datetime(["2026-07-01T06:00Z", "2026-07-01T07:00Z"], utc=True)
    E_mu = pd.DataFrame(
        {"AAA|BASE": [10.0, 10.0], "BBB|LINE": [1.0, 1.0]}, index=hours
    )
    return build_sf_mu_artifact(SF, E_mu)


def test_ranked_predicted_orders_and_dipole(client, fake_pool, configured_run,
                                            monkeypatch):
    monkeypatch.setattr(map_module, "_SP_COORDS",
                        {"N1": (29.7, -95.3), "N2": (32.6, -101.0),
                         "N3": (30.0, -99.0)})
    fake_pool.cursor.queue([{"sf_npz": _ranked_blob()}])   # artifact fetch
    fake_pool.cursor.queue([{"ws": WS}])                    # _resolve (geo run)
    fake_pool.cursor.queue([                                 # constraint_geo join
        {"constraint_key": "AAA|BASE", "ctype": "gtc",
         "core_lat": 30.5, "core_lon": -97.0},
    ])

    r = client.get("/map/constraints/ranked",
                   params={"run_id": "fc-v1", "day": "2026-07-01"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "fc-v1" and body["delivery_date"] == "2026-07-01"
    assert body["basis"] == "predicted" and body["n_ranked"] == 2

    cs = body["constraints"]
    assert [c["constraint_id"] for c in cs] == ["AAA|BASE", "BBB|LINE"]
    aaa = cs[0]
    assert aaa["rank"] == 1
    assert aaa["mu_mass"] == pytest.approx(20.0)
    assert aaa["reach"] == pytest.approx(1.41, abs=1e-4)
    assert aaa["congestion_contribution"] == pytest.approx(28.2, abs=1e-3)
    # N3 (+0.01 < 0.05*0.8) is below the floor → 2 members, not 3
    assert aaa["n_members"] == 2
    assert aaa["ctype"] == "gtc" and aaa["core_lat"] == 30.5
    # dipole: sink is the +SF end (N1), source the −SF end (N2)
    assert aaa["sink_lobe"]["peak_sf"] == pytest.approx(0.8)
    assert aaa["sink_lobe"]["lat"] == pytest.approx(29.7)
    assert aaa["source_lobe"]["peak_sf"] == pytest.approx(-0.6)
    assert aaa["source_lobe"]["lat"] == pytest.approx(32.6)
    # BBB unmatched in constraint_geo → null type, still ranked
    assert cs[1]["ctype"] is None


def test_ranked_realized_swaps_mu_series(client, fake_pool, configured_run,
                                         monkeypatch):
    """Realized basis keeps the SF structure but reweights by DAM shadow-price
    mass — enough to flip the order relative to predicted."""
    monkeypatch.setattr(map_module, "_SP_COORDS", {"N1": (29.7, -95.3)})
    fake_pool.cursor.queue([{"sf_npz": _ranked_blob()}])   # artifact fetch
    fake_pool.cursor.queue([                                 # realized mu mass
        {"key": "AAA|BASE", "mass": 1.0},
        {"key": "BBB|LINE", "mass": 100.0},
    ])
    fake_pool.cursor.queue([{"ws": WS}])                    # _resolve (geo run)
    fake_pool.cursor.queue([])                               # constraint_geo (none)

    r = client.get("/map/constraints/ranked",
                   params={"run_id": "fc-v1", "day": "2026-07-01",
                           "basis": "realized"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["basis"] == "realized"
    cs = body["constraints"]
    # BBB now leads: 100*0.70 = 70 > AAA 1*1.41 = 1.41
    assert [c["constraint_id"] for c in cs] == ["BBB|LINE", "AAA|BASE"]
    assert cs[0]["mu_mass"] == pytest.approx(100.0)


def test_ranked_503_when_no_artifact(client, fake_pool, configured_run):
    fake_pool.cursor.queue([])  # artifact fetch → None
    r = client.get("/map/constraints/ranked",
                   params={"run_id": "fc-v1", "day": "2026-07-01"})
    assert r.status_code == 503


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


@pytest.mark.integration
def test_overview_de_piles_and_types(real_client):
    """The overview positions each constraint at its |SF|² core, typed, with a
    signed top-k field. The core must actually de-pile — differ from the |SF|-mean
    centroid for most constraints (the whole reason it exists)."""
    body = real_client.get("/map/overview", params={"n": 70, "k": 16}).json()
    cs = body["constraints"]
    assert len(cs) == 70
    assert {c["ctype"] for c in cs} <= {"gtc", "transmission", "radial"}
    assert all(c["core_lat"] is not None for c in cs), "a served constraint has no core"
    # every node clears the default 0.15*peak floor and carries a signed sf
    for c in cs:
        assert c["nodes"], f"{c['constraint_key']} has no nodes"
        assert all(abs(n["sf"]) >= 0.15 * c["max_abs_sf"] - 1e-9 for n in c["nodes"])
    # the core sits somewhere other than the centroid for the clear majority
    moved = sum(1 for c in cs
                if abs(c["core_lat"] - c["lat"]) + abs(c["core_lon"] - c["lon"]) > 0.1)
    assert moved > len(cs) // 2, "core is not de-piling off the centroid"
