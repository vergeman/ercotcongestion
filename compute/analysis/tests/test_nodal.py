"""Golden tests for F4 — nodal hotspots and common nodes at 2026-06-30 HE17.

Hotspots use ``fixtures/june30_he17_nodal.npz`` (the full μ̂ + full nodal
congestion over all 1111 SPs, plus full SF columns for the top-10 hotspots so
each decomposes exactly). Common nodes reuse ``june30_he17_full.npz`` — the
HE17 top-10 constraints' full rows — and count SP confluence across their F2
extrema.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/analysis/tests/test_nodal.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.analysis.families import (
    common_nodes,
    constraint_node_extrema,
    nodal_hotspots,
)

FIXTURES = Path(__file__).parent / "fixtures"
HOUR = pd.Timestamp("2026-06-30T21:00:00", tz="UTC")


@pytest.fixture
def nodal():
    """(cong, hotspot_SF, mu) — congestion over all SPs, SF for the hotspots."""
    z = np.load(FIXTURES / "june30_he17_nodal.npz", allow_pickle=True)
    constraints = [str(c) for c in z["constraints"]]
    mu = pd.Series(z["mu"], index=constraints)
    cong = pd.Series(z["cong"], index=[str(s) for s in z["sp_names"]])
    SF = pd.DataFrame(z["hotspot_sf"], index=constraints,
                      columns=[str(s) for s in z["hotspot_sps"]])
    return cong, SF, mu


@pytest.fixture
def top10_extrema():
    """F2 output for each of the HE17 top-10 constraints."""
    z = np.load(FIXTURES / "june30_he17_full.npz", allow_pickle=True)
    constraints = [str(c) for c in z["constraints"]]
    hours = pd.DatetimeIndex([pd.Timestamp(h) for h in z["hours"]])
    mu = pd.DataFrame(z["e_mu"], index=hours, columns=constraints).loc[HOUR]
    SF = pd.DataFrame(z["sample_sf"],
                      index=[str(c) for c in z["sample_constraints"]],
                      columns=[str(s) for s in z["sp_names"]])
    return {key: constraint_node_extrema(SF.loc[key], mu[key]) for key in SF.index}


def test_f4_hotspots_and_cancellation(nodal):
    cong, SF, mu = nodal
    hs = nodal_hotspots(cong, SF, mu, top_n=8, top_drivers=3)
    by_sp = {h["settlement_point"]: h for h in hs}

    # The OLNEY node is the day's peak, reinforcing (net close to gross).
    top = hs[0]
    assert top["settlement_point"].startswith("OLNEY")
    assert top["cong"] == pytest.approx(118.24, abs=0.02)
    assert top["drivers"][0]["constraint_key"] == "6830__B|SGRMGRS8"
    assert top["net_gross_ratio"] > 0.6
    # net (Σ contributions) is exactly the reconstructed congestion.
    assert top["net"] == pytest.approx(top["cong"], abs=1e-4)

    # JUNCTION is a cancellation node: large gross, small net — constraints
    # fighting over one location.
    jct = by_sp["JUNCTION_RN"]
    assert jct["gross"] > 120
    assert abs(jct["net"]) < 45
    assert jct["net_gross_ratio"] < 0.35
    assert jct["net_gross_ratio"] < top["net_gross_ratio"]
    assert jct["drivers"][0]["constraint_key"] == "TREADW_YELWJC1_1|DBIGKEN5"


def test_f4_common_nodes(top10_extrema):
    cn = common_nodes(top10_extrema, min_count=2)
    by_sp = {c["settlement_point"]: c for c in cn}

    # Every returned node is touched by ≥2 constraints, ranked by count.
    assert all(c["count"] >= 2 for c in cn)
    assert [c["count"] for c in cn] == sorted((c["count"] for c in cn), reverse=True)

    # JUNORTH is the hour's confluence anchor — 4 independent constraints stack
    # on it; JUNCTION 3.
    assert cn[0]["settlement_point"] == "JUNORTH_RN"
    assert by_sp["JUNORTH_RN"]["count"] == 4
    assert "TREADW_YELWJC1_1|DBIGKEN5" in by_sp["JUNORTH_RN"]["constraints"]
    assert by_sp["JUNCTION_RN"]["count"] == 3


def test_common_nodes_min_count_filter():
    """A node in only one constraint's extrema is never a common node."""
    f2 = {
        "C1|X": {"import": [{"settlement_point": "A", "sf": -0.3, "contribution": 5.0}],
                 "export": []},
        "C2|Y": {"import": [{"settlement_point": "A", "sf": -0.2, "contribution": 3.0}],
                 "export": [{"settlement_point": "B", "sf": 0.4, "contribution": -6.0}]},
    }
    cn = common_nodes(f2, min_count=2)
    assert [c["settlement_point"] for c in cn] == ["A"]
    assert cn[0]["count"] == 2
    assert cn[0]["total_abs_contribution"] == pytest.approx(8.0)
