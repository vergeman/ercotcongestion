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
from fastapi import HTTPException

import pandas as pd

import map as map_module
from compute.projection.propagate import build_sf_mu_artifact
from models import MapMeta, MapOverview, ScoreboardHeadline

WS = datetime(2025, 11, 4, tzinfo=timezone.utc)
WE = datetime(2026, 7, 2, tzinfo=timezone.utc)

# The CT delivery day the click endpoints serve, and an instant inside it. 12:00Z
# is mid-afternoon CT on DAY; 03:00Z the next UTC date is still DAY in CT — the
# seam that 0143.1 got wrong and 0144 must keep right.
DAY = datetime(2026, 7, 1, tzinfo=timezone.utc).date()
DAY_T0 = datetime(2026, 7, 1, 5, tzinfo=timezone.utc)      # CT midnight (CDT)
DAY_MID = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
DAY_TAIL = datetime(2026, 7, 2, 3, tzinfo=timezone.utc)    # still CT July 1


def _artifact(sf: dict[str, list[float]], index: list[str],
              mu: dict[str, list[float]] | None = None, *,
              full_day: bool = False) -> bytes:
    """A day artifact: SF is constraints x nodes, E_mu hourly over the CT block.

    ``full_day`` gives the block all 24 CT hours (what a correctly cut artifact
    always has); the default two-hour block stands in for a partial one.
    """
    sf_df = pd.DataFrame(sf, index=index)
    hours = (pd.date_range(DAY_T0, periods=24, freq="h", tz="UTC") if full_day
             else pd.to_datetime([DAY_T0, DAY_MID], utc=True))
    mu_df = pd.DataFrame(mu or {key: [1.0] * len(hours) for key in index}, index=hours)
    return build_sf_mu_artifact(sf_df, mu_df)


def _queue_click_artifact(fake_pool, blob: bytes | None, *, geo=None,
                          reaches_geo: bool = True):
    """Queue what _click_artifact (+ _geo_metadata) fire, in order.

    The fake cursor is a single FIFO shared by every call in a test, so queue
    exactly what the request consumes: a call that returns early (no artifact, or
    an hour the block does not cover) never reaches the geo lookup, and a stray
    queued row would desync the next request.
    """
    fake_pool.cursor.queue([{"run_id": "mu-all-v1"}])   # _forecast_run_id
    fake_pool.cursor.queue([{"h": 1}])                  # coalesce horizon probe
    if blob is None:
        fake_pool.cursor.queue([])                      # no artifact row
        return
    fake_pool.cursor.queue([{"sf_npz": blob}])          # artifact fetch
    if reaches_geo:
        fake_pool.cursor.queue(geo or [])               # _geo_metadata


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


# ---- /map/exposures ------------------------------------------------------

def test_exposures_serves_the_requested_days_artifact(client, fake_pool):
    """0144: exposures read the CT delivery day's artifact, so the DetailCard
    matches /matrix/frame at the same node and interval. Before this they always
    served the newest sf_window_meta window whatever `t` said."""
    blob = _artifact(
        {"LZ_WEST": [0.72, -0.31, 0.05], "LZ_NORTH": [0.10, 0.40, 0.02]},
        ["CONSTR_A", "CONSTR_B", "CONSTR_C"],
    )
    _queue_click_artifact(fake_pool, blob, geo=[
        {"constraint_key": "CONSTR_A", "ctype": "gtc", "n_rail": 3, "peak_offrail": 0.1},
    ])

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "k": 2, "t": DAY_MID.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sp"] == "LZ_WEST" and body["k"] == 2
    assert body["available"] is True
    assert body["run_id"] == "mu-all-v1"
    # §6: the unsigned headline is over ALL constraints, independent of k.
    assert body["node_max_abs_sf"] == pytest.approx(0.72)
    # Ranked by |sf|, signs preserved, and cut to k.
    assert [e["constraint_key"] for e in body["exposures"]] == ["CONSTR_A", "CONSTR_B"]
    assert body["exposures"][1]["sf"] == pytest.approx(-0.31)
    # ctype stays structural (constraint_geo); the magnitudes are per-day, taken
    # off the artifact row exactly as /matrix/frame reports them.
    assert body["exposures"][0]["ctype"] == "gtc"
    assert body["exposures"][0]["max_abs_sf"] == pytest.approx(0.72)
    assert body["exposures"][0]["binding_hours"] == 2
    # The window now bounds the day's block, not a rolling refit — and the
    # rolling fit's confidence numbers no longer describe these values.
    assert body["window_start"].startswith("2026-07-01T05:00")
    assert body["oos_r2"] is None and body["sf_stability"] is None


def test_exposures_resolves_the_ct_day_not_the_utc_date(client, fake_pool):
    """The CT evening hours (00:00-04:00Z of the next UTC date) belong to the
    same delivery day; a UTC cut here would repeat 0143.1 on the map."""
    blob = _artifact({"LZ_WEST": [0.72]}, ["CONSTR_A"], full_day=True)
    _queue_click_artifact(fake_pool, blob)

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": DAY_TAIL.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["available"] is True
    # The horizon probe is the first query carrying the resolved day.
    probe = [q for q in fake_pool.cursor.queries if "min(horizon)" in q[0]][0]
    assert probe[1] == ("mu-all-v1", DAY)


def test_exposures_reports_a_day_with_no_artifact(client, fake_pool):
    """Days before the artifact history (pre-2025) return an explicit empty, not
    a silent fallback to a rolling window on a different basis."""
    _queue_click_artifact(fake_pool, None)

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": "2024-03-01T12:00:00Z"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert body["unavailable_reason"] == "artifact_missing"
    assert body["exposures"] == []


# An hour the block does not cover must be unavailable on the map exactly as
# /matrix/frame reports it. A correctly cut CT block covers all 24 hours of its
# day, so this only bites on a misaligned or partial block — but answering from
# the day's SF while the matrix reports nothing there is the map/matrix
# disagreement 0144 exists to remove. One endpoint per test: the decoded-artifact
# cache is cleared between tests but not within one, so a second request in the
# same test would skip the blob fetch and desync the shared cursor.
UNCOVERED = datetime(2026, 7, 1, 20, tzinfo=timezone.utc)   # same CT day, not in E_mu


def test_exposures_matches_the_matrix_verdict_on_an_uncovered_hour(client, fake_pool):
    _queue_click_artifact(fake_pool, _artifact({"LZ_WEST": [0.72]}, ["CONSTR_A"]),
                          reaches_geo=False)

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": UNCOVERED.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert body["unavailable_reason"] == "interval_not_in_artifact"
    assert body["exposures"] == []


def test_reach_matches_the_matrix_verdict_on_an_uncovered_hour(client, fake_pool):
    _queue_click_artifact(fake_pool, _artifact({"LZ_WEST": [0.72]}, ["CONSTR_A"]))

    r = client.get("/map/reach",
                   params={"constraint": "CONSTR_A", "t": UNCOVERED.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert body["unavailable_reason"] == "interval_not_in_artifact"
    assert body["sps"] == []


def test_exposures_without_t_uses_the_latest_built_day(client, fake_pool):
    blob = _artifact({"LZ_WEST": [0.72]}, ["CONSTR_A"])
    fake_pool.cursor.queue([{"run_id": "mu-all-v1"}])   # _forecast_run_id
    fake_pool.cursor.queue([{"d": DAY}])                # _latest_artifact_day
    fake_pool.cursor.queue([{"h": 1}])
    fake_pool.cursor.queue([{"sf_npz": blob}])
    fake_pool.cursor.queue([])

    r = client.get("/map/exposures", params={"sp": "LZ_WEST"})
    assert r.status_code == 200, r.text
    assert r.json()["available"] is True


@pytest.mark.parametrize("counts, reason", [
    # The run forecast the day but never this node -> it did not exist yet.
    ({"sp_rows": 0, "day_rows": 26880}, "sp_not_in_service"),
    # Forecast, but dropped by the fit.
    ({"sp_rows": 24, "day_rows": 26880}, "sp_not_in_fit"),
    # The run forecast nothing that day: the two are indistinguishable.
    ({"sp_rows": 0, "day_rows": 0}, "sp_not_in_fit"),
])
def test_exposures_reports_why_a_node_has_no_sf(client, fake_pool, counts, reason):
    """0146: its own reason, so "no SF here" cannot read as "nothing bound"."""
    blob = _artifact({"LZ_WEST": [0.72]}, ["CONSTR_A"])
    _queue_click_artifact(fake_pool, blob, reaches_geo=False)
    fake_pool.cursor.queue([counts])                    # _absent_sp_reason

    r = client.get("/map/exposures",
                   params={"sp": "NOT_A_NODE", "t": DAY_MID.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert body["unavailable_reason"] == reason
    assert body["exposures"] == []


def test_exposures_stays_available_for_a_node_that_bound_nothing(client, fake_pool):
    """The case 0146 must keep distinct: in the fit, mu all zero."""
    blob = _artifact({"LZ_WEST": [0.72]}, ["CONSTR_A"],
                     mu={"CONSTR_A": [0.0, 0.0]})
    _queue_click_artifact(fake_pool, blob, reaches_geo=False)

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": DAY_MID.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["unavailable_reason"] is None
    assert body["exposures"] == []


# ---- /map/reach ----------------------------------------------------------

def test_reach_signed_with_coords(client, fake_pool, monkeypatch):
    monkeypatch.setattr(map_module, "_SP_COORDS",
                        {"LZ_WEST": (31.9, -102.1), "LZ_NORTH": (33.0, -97.0)})
    monkeypatch.setattr(map_module, "_SP_METADATA", {
        "LZ_WEST": ("load_zone", "west"), "LZ_NORTH": ("load_zone", "north"),
    })
    blob = _artifact(
        {"LZ_WEST": [0.72], "LZ_NORTH": [-0.30]},
        ["CONSTR_A"],
        mu={"CONSTR_A": [1.0, 17.25]},
    )
    _queue_click_artifact(fake_pool, blob, geo=[
        {"constraint_key": "CONSTR_A", "ctype": "gtc", "n_rail": 4, "peak_offrail": 0.2},
    ])
    fake_pool.cursor.queue([{"shadow_price": 12.0}])

    r = client.get("/map/reach",
                   params={"constraint": "CONSTR_A", "k": 5, "t": DAY_MID.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["constraint_key"] == "CONSTR_A"
    assert body["available"] is True
    assert body["max_abs_sf"] == pytest.approx(0.72)
    assert body["binding_hours"] == 2          # per-day, from the artifact E_mu
    assert body["shadow_price"] == pytest.approx(17.25)  # cursor hour, not day mass
    assert body["dam_mu"] == pytest.approx(12.0)
    assert body["forecast_error"] == pytest.approx(5.25)
    assert body["daily_mu_rank"] == 1 and body["daily_mu_sum"] == pytest.approx(18.25)
    assert body["import_members"] == 1 and body["export_members"] == 1
    assert body["ctype"] == "gtc" and body["n_rail"] == 4   # structural, from geo
    assert body["oos_r2"] is None
    sps = body["sps"]
    assert sps[0] == {
        "settlement_point": "LZ_WEST", "sf": pytest.approx(0.72),
        "lat": 31.9, "lon": -102.1,
        "settlement_point_type": "load_zone", "load_zone": "west",
    }
    assert sps[1]["sf"] == pytest.approx(-0.30) and sps[1]["lat"] == 33.0
    assert sps[1]["load_zone"] == "north"


def test_reach_full_mode_drops_the_limit_and_is_never_truncated(client, fake_pool):
    """0139/0001: the matrix Read pane needs the constraint's complete reach
    (bounded only by min_frac), not a top-k display slice — a fixed k ceiling
    is a guess that can go stale as the node universe grows."""
    blob = _artifact({f"SP{i}": [0.1] for i in range(600)}, ["CONSTR_A"])
    _queue_click_artifact(fake_pool, blob)

    r = client.get("/map/reach", params={"constraint": "CONSTR_A", "full": True,
                                        "min_frac": 0, "t": DAY_MID.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["sps"]) == 600
    assert body["truncated"] is False


def test_reach_bounded_mode_flags_truncation_when_more_nodes_exist(client, fake_pool):
    blob = _artifact({"A": [0.5], "B": [0.4], "C": [0.3]}, ["CONSTR_A"])
    _queue_click_artifact(fake_pool, blob)

    r = client.get("/map/reach", params={"constraint": "CONSTR_A", "k": 2,
                                        "t": DAY_MID.isoformat()})
    body = r.json()
    assert [sp["settlement_point"] for sp in body["sps"]] == ["A", "B"]
    assert body["truncated"] is True


def test_reach_bounded_mode_is_not_truncated_when_exactly_k_nodes_exist(client, fake_pool):
    blob = _artifact({"A": [0.5]}, ["CONSTR_A"])
    _queue_click_artifact(fake_pool, blob)

    r = client.get("/map/reach", params={"constraint": "CONSTR_A", "k": 5,
                                        "t": DAY_MID.isoformat()})
    body = r.json()
    assert len(body["sps"]) == 1
    assert body["truncated"] is False


def test_reach_min_frac_floors_off_the_days_own_peak(client, fake_pool):
    """The noise floor is a fraction of the constraint's peak |SF| in *this day's*
    artifact, so a weakly-fit constraint is not padded with noise-floor nodes."""
    blob = _artifact({"A": [1.0], "B": [0.5], "C": [0.02]}, ["CONSTR_A"])
    _queue_click_artifact(fake_pool, blob)

    r = client.get("/map/reach", params={"constraint": "CONSTR_A", "min_frac": 0.1,
                                        "t": DAY_MID.isoformat()})
    body = r.json()
    assert [sp["settlement_point"] for sp in body["sps"]] == ["A", "B"]


def test_reach_abs_floor_cuts_below_an_absolute_sf(client, fake_pool):
    """abs_floor combines with min_frac as max(min_frac*peak, abs_floor), so a
    noise-peak constraint's tail is cut even when the relative floor is permissive
    (0147). Here min_frac=0 would keep every node; abs_floor=0.3 drops C."""
    blob = _artifact({"A": [1.0], "B": [0.5], "C": [0.2]}, ["CONSTR_A"])
    _queue_click_artifact(fake_pool, blob)

    r = client.get("/map/reach", params={"constraint": "CONSTR_A", "min_frac": 0.0,
                                        "abs_floor": 0.3, "t": DAY_MID.isoformat()})
    body = r.json()
    assert [sp["settlement_point"] for sp in body["sps"]] == ["A", "B"]


def test_reach_reports_a_day_with_no_artifact_and_no_earlier_build(client, fake_pool):
    """A date before the artifact history: the requested day has no artifact AND
    nothing was built earlier, so the nearest-past fallback finds nothing and the
    reach reports an explicit empty rather than inventing a member set."""
    _queue_click_artifact(fake_pool, None)
    fake_pool.cursor.queue([{"d": None}])   # _nearest_past_artifact_day → none earlier

    r = client.get("/map/reach", params={"constraint": "CONSTR_A",
                                         "t": "2024-03-01T12:00:00Z"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert body["unavailable_reason"] == "artifact_missing"
    assert body["sps"] == []


def test_reach_falls_back_to_nearest_past_day_when_the_day_has_no_artifact(
    client, fake_pool, monkeypatch
):
    """A lagging/failed forecast job leaves the cursor's day with no artifact. SF is
    topology-driven, so the reach serves the nearest EARLIER built day's members
    (basis='nearest_past') instead of a blank card, with window_start reporting the
    day actually served so the client can label it."""
    monkeypatch.setattr(map_module, "_SP_COORDS", {"LZ_WEST": (31.9, -102.1)})
    monkeypatch.setattr(map_module, "_SP_METADATA", {"LZ_WEST": ("load_zone", "west")})
    _queue_click_artifact(fake_pool, None)            # requested day: no artifact
    fake_pool.cursor.queue([{"d": DAY}])              # _nearest_past_artifact_day
    fake_pool.cursor.queue([{"h": 1}])               # fallback load's horizon probe
    blob = _artifact({"LZ_WEST": [0.72]}, ["CONSTR_A"], full_day=True)
    fake_pool.cursor.queue([{"sf_npz": blob}])        # fallback artifact fetch
    fake_pool.cursor.queue([                          # _geo_metadata
        {"constraint_key": "CONSTR_A", "ctype": "gtc", "n_rail": 4, "peak_offrail": 0.2},
    ])

    r = client.get("/map/reach", params={"constraint": "CONSTR_A",
                                         "t": "2026-09-01T12:00:00Z"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["basis"] == "nearest_past"
    assert body["shadow_price"] is None  # fallback SF is structural, not stale μ
    assert body["window_start"].startswith(DAY.isoformat())
    assert [sp["settlement_point"] for sp in body["sps"]] == ["LZ_WEST"]


def test_reach_reports_a_constraint_absent_from_the_day(client, fake_pool):
    blob = _artifact({"A": [0.5]}, ["CONSTR_A"])
    _queue_click_artifact(fake_pool, blob, geo=[
        {"constraint_key": "OTHER", "ctype": "gtc", "n_rail": 1, "peak_offrail": 0.0},
    ])

    r = client.get("/map/reach", params={"constraint": "OTHER",
                                         "t": DAY_MID.isoformat()})
    body = r.json()
    assert body["available"] is False
    assert body["unavailable_reason"] == "constraint_not_in_artifact"
    assert body["sps"] == []


# ---- /map/overview -------------------------------------------------------

def test_overview_cores_types_and_grouping(client, fake_pool, configured_run,
                                           monkeypatch):
    """The bulk overview: each constraint typed, with its signed top-k node field
    grouped from the single ANY(keys) node query, and the per-constraint min_frac
    floor dropping the noise-floor node."""
    monkeypatch.setattr(map_module, "_SP_COORDS",
                        {"N1": (29.7, -95.3), "N2": (32.6, -101.0),
                         "N3": (30.0, -99.0), "N4": (33.0, -97.0)})
    monkeypatch.setattr(map_module, "_SP_METADATA", {"N1": ("RN", "houston")})
    fake_pool.cursor.queue([{"ws": WS}])            # _resolve
    fake_pool.cursor.queue([_meta_row()])           # _meta_row
    fake_pool.cursor.queue([                         # top-n constraint_geo rows
        {"constraint_key": "AAA|BASE CASE", "ctype": "gtc", "binding_hours": 300,
         "max_abs_sf": 0.50},
        {"constraint_key": "BBB|LINE", "ctype": "transmission", "binding_hours": 200,
         "max_abs_sf": 0.40},
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
    # the noise-floor node (0.02 < 0.15*0.50) is dropped; the two real ones stay
    assert [n["settlement_point"] for n in a["nodes"]] == ["N1", "N2"]
    assert a["nodes"][1]["sf"] == -0.40 and a["nodes"][1]["lat"] == 32.6  # opposite end, coord joined
    assert a["nodes"][0]["settlement_point_type"] == "RN"
    assert a["nodes"][0]["load_zone"] == "houston"
    assert b["ctype"] == "transmission" and [n["settlement_point"] for n in b["nodes"]] == ["N4"]


def test_overview_truncates_to_k_nodes(client, fake_pool, configured_run, monkeypatch):
    """k caps the per-constraint field even when more nodes clear the floor."""
    monkeypatch.setattr(map_module, "_SP_COORDS", {})
    fake_pool.cursor.queue([{"ws": WS}])
    fake_pool.cursor.queue([_meta_row()])
    fake_pool.cursor.queue([{
        "constraint_key": "AAA|c", "ctype": "transmission", "binding_hours": 100,
        "max_abs_sf": 1.0,
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
    from compute.projection.propagate import build_sf_mu_artifact

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
    fake_pool.cursor.queue([{"h": 1}])                     # 0123: coalesce probe
    fake_pool.cursor.queue([{"sf_npz": _ranked_blob()}])   # artifact fetch
    fake_pool.cursor.queue([{"ws": WS}])                    # _resolve (geo run)
    fake_pool.cursor.queue([                                 # constraint_geo join
        {"constraint_key": "AAA|BASE", "ctype": "gtc"},
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
    assert aaa["binding_hours"] == 2
    assert aaa["reach"] == pytest.approx(1.41, abs=1e-4)
    assert aaa["congestion_contribution"] == pytest.approx(28.2, abs=1e-3)
    # N3 (+0.01 < 0.05*0.8) is below the floor → 2 members, not 3
    assert aaa["n_members"] == 2
    assert aaa["ctype"] == "gtc"
    # dipole: one +SF node (N1) on the export side, one −SF node (N2) on the import
    assert aaa["n_export"] == 1
    assert aaa["n_import"] == 1
    # BBB unmatched in constraint_geo → null type, still ranked
    assert cs[1]["ctype"] is None


def test_ranked_realized_swaps_mu_series(client, fake_pool, configured_run,
                                         monkeypatch):
    """Realized basis keeps the SF structure but reweights by DAM shadow-price
    mass — enough to flip the order relative to predicted."""
    monkeypatch.setattr(map_module, "_SP_COORDS", {"N1": (29.7, -95.3)})
    fake_pool.cursor.queue([{"h": 1}])                     # 0123: coalesce probe
    fake_pool.cursor.queue([{"sf_npz": _ranked_blob()}])   # artifact fetch
    fake_pool.cursor.queue([                                 # realized mu mass
        {"constraint_name": " AAA ", "contingency_name": " BASE ", "mass": 1.0,
         "binding_hours": 1},
        {"constraint_name": "BBB", "contingency_name": "LINE", "mass": 100.0,
         "binding_hours": 3},
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
    assert cs[0]["binding_hours"] == 3
    # The basis changes μ-derived fields but not the artifact's SF summaries.
    assert cs[0]["reach"] == pytest.approx(0.70)


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
    overview = real_client.get("/map/overview", params={"n": 1, "k": 1}).json()
    assert overview["constraints"], "no constraints served for map-v1"
    c = overview["constraints"][0]["constraint_key"]

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
def test_overview_types_and_node_field(real_client):
    """The overview draws each constraint as a typed mark over a signed top-k node
    field. Position now comes from the nodes themselves (the client anchors the
    mark on them), so there is no core/centroid to assert — just the type and a
    non-empty node field that clears the floor."""
    body = real_client.get("/map/overview", params={"n": 70, "k": 16}).json()
    cs = body["constraints"]
    assert len(cs) == 70
    assert {c["ctype"] for c in cs} <= {"gtc", "transmission", "radial"}
    # every node clears the default 0.15*peak floor and carries a signed sf
    for c in cs:
        assert c["nodes"], f"{c['constraint_key']} has no nodes"
        assert all(abs(n["sf"]) >= 0.15 * c["max_abs_sf"] - 1e-9 for n in c["nodes"])
        # the client positions the mark from these coords
        assert all(n["lat"] is not None and n["lon"] is not None for n in c["nodes"])


# --------------------------------------------------------------------------
# /map/summary (0137) — mirrors test_analysis.py's brief-day composition
# test and test_scoreboard_summary.py: monkeypatch the section handlers
# directly rather than threading fake rows through their own (already
# separately tested) query logic. `MapSummaryResponse(...)` is constructed
# — and so validated by Pydantic — inside `get_map_summary` itself, so the
# fakes must return real (if minimal) instances of each section's model.
# --------------------------------------------------------------------------

TOPOLOGY = {"type": "FeatureCollection", "features": []}
OVERVIEW = MapOverview(run_id="map-v1", window_start=WS, window_end=WE, n=70, k=6, constraints=[])
META = MapMeta(run_id="map-v1", window_start=WS, window_end=WE)
HEADLINE = ScoreboardHeadline(run_id="r", regime="all", as_of_week=WS.date(), windows=[])


def test_summary_calls_each_section_with_its_existing_literal_defaults(monkeypatch):
    """Each handler is called in-process, bypassing FastAPI's dependency
    injection, so any omitted parameter would receive its raw ``Query(...)``
    object instead of the literal default. Assert the exact args every
    section receives — overview at (70, 6, 0.15), matching MapWorkspace.tsx's
    own override of the single-section endpoint's k=16 default; headline at
    (None, "all"). Keyed by name since overview/meta/headline run on a thread
    pool (not in submission order)."""
    calls: dict[str, tuple] = {}

    def _fake(name, result):
        def _handler(*args):
            calls[name] = args
            return result
        return _handler

    monkeypatch.setattr(map_module, "get_map_overview", _fake("overview", OVERVIEW))
    monkeypatch.setattr(map_module, "get_map_meta", _fake("meta", META))
    monkeypatch.setattr(map_module, "get_scoreboard_headline", _fake("headline", HEADLINE))
    monkeypatch.setattr(map_module, "get_or_build_topology", lambda: TOPOLOGY)

    body = map_module.get_map_summary()

    assert calls == {
        "overview": (70, 6, 0.15),
        "meta": (),
        "headline": (None, "all"),
    }
    assert body.topology == TOPOLOGY
    assert body.overview == OVERVIEW
    assert body.meta == META
    assert body.headline == HEADLINE
    assert body.availability['overview'].available is True
    assert body.availability['overview'].run_id == 'map-v1'


def test_summary_turns_a_sections_503_into_a_null_field_without_failing_the_rest(
    monkeypatch,
):
    """No SF window built yet must not take down the sections that do have
    data — same soft-fail the client already applies per single-section
    endpoint (503 -> null)."""
    def _unavailable(*args):
        raise HTTPException(status_code=503, detail="no window built")

    monkeypatch.setattr(map_module, "get_map_overview", _unavailable)
    monkeypatch.setattr(map_module, "get_map_meta", lambda: META)
    monkeypatch.setattr(map_module, "get_scoreboard_headline", lambda *a: HEADLINE)
    monkeypatch.setattr(map_module, "get_or_build_topology", lambda: TOPOLOGY)

    body = map_module.get_map_summary()

    assert body.overview is None
    assert body.meta == META
    assert body.availability['overview'].available is False
    assert body.availability['overview'].unavailable_reason == 'source_unavailable'
    assert body.headline == HEADLINE
    assert body.topology == TOPOLOGY


def test_summary_does_not_soft_fail_a_topology_build_error(monkeypatch):
    """Topology was never a null-and-continue case for the client
    (`fetchTopology` always threw on non-503 failure) — the bundle preserves
    that instead of inventing a new empty state for it."""
    monkeypatch.setattr(map_module, "get_map_overview", lambda *a: OVERVIEW)
    monkeypatch.setattr(map_module, "get_map_meta", lambda: META)
    monkeypatch.setattr(map_module, "get_scoreboard_headline", lambda *a: HEADLINE)

    def _broken():
        raise RuntimeError("topology cache build failed")

    monkeypatch.setattr(map_module, "get_or_build_topology", _broken)

    with pytest.raises(RuntimeError):
        map_module.get_map_summary()


# ---- 0145: ranking basis ------------------------------------------------
#
# The three surfaces read identical SF values and only ever differed in what
# they sorted by, which is why they read as a data disagreement. These fix the
# node card on "what actually drove this node" and keep the structural view
# reachable — and named — rather than implicit.

# CONSTR_QUIET has the largest |SF| but never binds; CONSTR_LIVE has a smaller
# |SF| and carries all of the node's actual congestion. Under the old |SF|
# ordering the card led with the constraint that did nothing.
def _driver_artifact() -> bytes:
    return _artifact(
        {"LZ_WEST": [-1.0, 0.40, 0.20], "LZ_NORTH": [0.05, 0.10, 0.30]},
        ["CONSTR_QUIET", "CONSTR_LIVE", "CONSTR_SMALL"],
        mu={"CONSTR_QUIET": [0.0, 0.0], "CONSTR_LIVE": [10.0, 50.0],
            "CONSTR_SMALL": [1.0, 4.0]},
    )


def test_exposures_rank_contribution_drops_constraints_that_never_bound(client, fake_pool):
    """The default basis answers "what drove this node", so a constraint with
    mu=0 is absent rather than ranked first on |SF| alone (0145)."""
    _queue_click_artifact(fake_pool, _driver_artifact())

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": DAY_MID.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rank"] == "contribution"
    keys = [e["constraint_key"] for e in body["exposures"]]
    assert "CONSTR_QUIET" not in keys
    # -SF * mu at 12:00Z: LIVE = -0.40*50 = -20.0, SMALL = -0.20*4 = -0.8.
    assert keys == ["CONSTR_LIVE", "CONSTR_SMALL"]
    live = body["exposures"][0]
    assert live["contribution"] == pytest.approx(-20.0)
    assert live["mu"] == pytest.approx(50.0)
    assert live["sf"] == pytest.approx(0.40)
    # Gross magnitude supplies a bounded driver share even when positive and
    # negative terms offset. It includes every constraint, not just top-k.
    assert body["node_gross_total"] == pytest.approx(20.8)
    assert "node_total" not in body
    # The unsigned structural headline is unchanged by the ranking basis.
    assert body["node_max_abs_sf"] == pytest.approx(1.0)


def test_exposures_rank_contribution_uses_the_cursor_hour_not_the_day(client, fake_pool):
    """A node card explains the interval on the scrubber; summing the block
    would answer a different question than the one the click asked."""
    _queue_click_artifact(fake_pool, _driver_artifact())

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": DAY_T0.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    # 05:00Z is the block's first hour: LIVE mu = 10, not the 60 of the day sum.
    live = body["exposures"][0]
    assert live["mu"] == pytest.approx(10.0)
    assert live["contribution"] == pytest.approx(-4.0)


def test_exposures_rank_sf_keeps_the_structural_ordering(client, fake_pool):
    """The structural view stays reachable: it answers "what could move this
    node", which a quiet day erases from the contribution list entirely."""
    _queue_click_artifact(fake_pool, _driver_artifact())

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": DAY_MID.isoformat(), "rank": "sf"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rank"] == "sf"
    assert [e["constraint_key"] for e in body["exposures"]] == [
        "CONSTR_QUIET", "CONSTR_LIVE", "CONSTR_SMALL"]
    # No hour is implied by a structural ranking, so neither field is invented.
    assert body["exposures"][0]["contribution"] is None
    assert body["exposures"][0]["mu"] is None
    assert body["node_gross_total"] is None


def test_exposures_marks_shift_factors_pinned_at_the_clip_cap(client, fake_pool):
    """|SF| = SF_ABS_CAP is a bound the ridge hit, not a measurement — and it
    always sorts first under rank=sf, so it has to be visibly flagged (0145)."""
    _queue_click_artifact(fake_pool, _driver_artifact())

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": DAY_MID.isoformat(), "rank": "sf"})
    assert r.status_code == 200, r.text
    flags = {e["constraint_key"]: e["sf_clipped"] for e in r.json()["exposures"]}
    assert flags == {"CONSTR_QUIET": True, "CONSTR_LIVE": False, "CONSTR_SMALL": False}


def test_exposures_rank_contribution_ranks_by_magnitude_across_signs(client, fake_pool):
    """Import and export both drive a node; ordering is on |contribution| so a
    large negative term is not sorted below a small positive one."""
    blob = _artifact(
        {"LZ_WEST": [0.50, -0.60], "LZ_NORTH": [0.10, 0.20]},
        ["CONSTR_POS", "CONSTR_NEG"],
        mu={"CONSTR_POS": [1.0, 10.0], "CONSTR_NEG": [1.0, 30.0]},
    )
    _queue_click_artifact(fake_pool, blob)

    r = client.get("/map/exposures",
                   params={"sp": "LZ_WEST", "t": DAY_MID.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    # POS = -0.50*10 = -5.0; NEG = 0.60*30 = +18.0.
    assert [e["constraint_key"] for e in body["exposures"]] == ["CONSTR_NEG", "CONSTR_POS"]
    assert body["exposures"][0]["contribution"] == pytest.approx(18.0)
    assert body["node_gross_total"] == pytest.approx(23.0)
