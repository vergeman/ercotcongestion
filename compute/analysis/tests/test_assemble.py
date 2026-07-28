"""build_brief wiring on a small synthetic artifact.

Golden *numbers* are pinned by the family tests; this checks the assembly
contract — every hour carries F1 constraints (each with F2 nodes + F3 stats), F4
hotspots + common nodes, the F5a dipole, and the F5b/F6 placeholders; the day
roll-up carries ranks, peak hours, and the watchlist; floats are rounded.
"""
import pandas as pd

from compute.analysis.assemble import build_brief
from compute.analysis.metadata import load_sp_metadata

CONSTRAINTS = ["C1|A", "C2|B", "C3|C", "C4|D"]
SPS = ["N1", "N2", "N3", "N4", "HB_WEST", "HB_HOUSTON"]


def _artifact():
    SF = pd.DataFrame(
        [[-0.5, 0.4, -0.1, 0.2, -0.3, 0.3],
         [0.2, -0.6, 0.3, -0.2, -0.4, 0.1],
         [-0.3, 0.1, -0.5, 0.4, 0.2, -0.4],
         [0.1, -0.2, 0.6, -0.3, -0.1, 0.2]],
        index=CONSTRAINTS, columns=SPS,
    )
    hours = pd.date_range("2026-06-30", periods=2, freq="h", tz="UTC")
    E_mu = pd.DataFrame([[50.0, 30.0, 20.0, 10.0],
                         [40.0, 60.0, 10.0, 25.0]], index=hours, columns=CONSTRAINTS)
    return SF, E_mu


def _brief():
    SF, E_mu = _artifact()
    metadata = load_sp_metadata(SPS, csv_path="/nonexistent.csv")
    return build_brief(SF, E_mu, metadata, run_id="run-x",
                       delivery_date="2026-06-30", horizon=1,
                       watchlist_min_hours=1)


def test_provenance_and_hour_axis():
    b = _brief()
    p = b["provenance"]
    assert p["run_id"] == "run-x" and p["horizon"] == 1 and p["mu_basis"] == "forecast"
    assert (p["n_constraints"], p["n_settlement_points"], p["n_hours"]) == (4, 6, 2)
    assert p["dam_match_coverage"] is None
    assert set(b["hours"]) == {"2026-06-30T00:00:00+00:00", "2026-06-30T01:00:00+00:00"}


def test_each_hour_carries_every_family():
    entry = _brief()["hours"]["2026-06-30T00:00:00+00:00"]
    assert set(entry) == {"constraints", "hotspots", "common_nodes",
                          "hub_dipole", "best_pair", "after_action"}
    assert entry["best_pair"] is None and entry["after_action"] is None

    # F1 constraints ordered by hour_rank, each with F2 nodes + F3 stats.
    cons = entry["constraints"]
    assert [c["hour_rank"] for c in cons] == list(range(1, len(cons) + 1))
    top = cons[0]
    assert {"import", "export"} <= set(top["nodes"])
    assert {"reach", "top5_share", "max_contrast"} <= set(top["stats"])

    # F4 hotspots: net equals reconstructed cong; F5a dipole spans the two hubs.
    hs = entry["hotspots"][0]
    assert {"cong", "gross", "net", "net_gross_ratio", "drivers"} <= set(hs)
    dip = entry["hub_dipole"]
    assert {dip["min"]["settlement_point"], dip["max"]["settlement_point"]} == {
        "HB_WEST", "HB_HOUSTON"}
    assert dip["spread"] >= 0
    assert isinstance(entry["common_nodes"], list)


def test_day_rollup():
    day = _brief()["day"]
    ranks = day["daily_ranks"]
    assert [r["daily_rank"] for r in ranks] == list(range(1, len(ranks) + 1))
    scores = [r["daily_score"] for r in ranks]
    assert scores == sorted(scores, reverse=True)

    assert day["peak_hours"]["by_hour_score"] in _brief()["hours"]
    assert day["peak_hours"]["by_dipole_spread"] in _brief()["hours"]

    # watchlist_min_hours=1, so every top-ranked constraint recurs enough to list.
    assert {"constraints", "nodes"} == set(day["watchlist"])
    assert all(w["hours"] >= 1 for w in day["watchlist"]["constraints"])


def test_floats_are_rounded():
    b = _brief()
    dip = b["hours"]["2026-06-30T00:00:00+00:00"]["hub_dipole"]
    # Every stored float carries at most 4 decimals.
    assert dip["spread"] == round(dip["spread"], 4)
    for hub in dip["hubs"]:
        assert hub["cong"] == round(hub["cong"], 4)
