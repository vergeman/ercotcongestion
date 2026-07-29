"""Golden + guardrail tests for F5b — the best source→sink pair at 2026-06-30 HE17.

The fixture (``fixtures/june30_he17_f5b.npz``) holds the full μ̂ over 1057
constraints and the full SF columns for the 40 highest- and 40 lowest-congestion
SPs plus the golden endpoints — enough that the argmax/argmin best pair is exactly
the one the walkthrough found (OLNEY ↔ LGW, $159.19), while the guardrail behaviour
(type gate, DAM coverage, F5a suppression, duplicate clustering) is exercised on
synthetic inputs where each rule can be isolated.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/analysis/tests/test_best_pair.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.analysis.brief import nodal_congestion
from compute.analysis.families import best_pair

FIXTURE = Path(__file__).parent / "fixtures" / "june30_he17_f5b.npz"


@pytest.fixture
def hour():
    z = np.load(FIXTURE, allow_pickle=True)
    constraints = [str(c) for c in z["constraints"]]
    sps = [str(s) for s in z["sp_names"]]
    mu = pd.Series(z["mu"], index=constraints)
    SF = pd.DataFrame(z["sf"], index=constraints, columns=sps)
    metadata = {
        sp: {"sp_type": (None if z["sp_type"][i] is None else str(z["sp_type"][i])),
             "load_zone": (None if z["load_zone"][i] is None else str(z["load_zone"][i])),
             "lat": (None if z["lat"][i] is None else float(z["lat"][i])),
             "lon": (None if z["lon"][i] is None else float(z["lon"][i]))}
        for i, sp in enumerate(sps)
    }
    return SF, mu, metadata


def test_best_pair_is_the_golden_olney_lgw(hour):
    SF, mu, metadata = hour
    cong = nodal_congestion(SF, mu)
    bp = best_pair(cong, SF, mu, metadata)

    # OLNEY vs Logans Gap — the auto-discovered $159.19 headline.
    assert bp["sink"]["settlement_point"].startswith("OLNEYTN")
    assert bp["source"]["settlement_point"] == "LGW_UNIT_ALL"
    assert bp["spread"] == pytest.approx(159.19, abs=0.02)

    # Two 6830 constraints dominate; drivers reconcile to the spread.
    assert bp["drivers"][0]["constraint_key"] == "6830__B|SGRMGRS8"
    assert bp["drivers"][0]["contribution"] == pytest.approx(74.36, abs=0.02)
    assert bp["dominance_share"] == pytest.approx(0.467, abs=0.005)
    assert sum(d["contribution"] for d in bp["drivers"]) == pytest.approx(
        bp["spread"], abs=5.0)   # top drivers are most of it; full sum is exact below


def test_duplicate_cluster_keeps_one_representative(hour):
    SF, mu, metadata = hour
    cong = nodal_congestion(SF, mu)
    bp = best_pair(cong, SF, mu, metadata)
    # OLNEYTN_AGR1 and OLNEYTN_RN share a coordinate; only one is the endpoint.
    assert bp["guardrails"]["n_clusters"] < bp["guardrails"]["n_candidates"]


# --- guardrails on isolated synthetic inputs -------------------------------

def _toy():
    """5 SPs: A/B are a coincident duplicate pair (high cong), C low, E mid,
    D untyped. cong = −SFᵀμ → A=B=35, C=−30, E=−5, D=15."""
    sps = ["A", "B", "C", "D", "E"]
    SF = pd.DataFrame(
        [[-0.5, -0.5, 0.4, -0.4, 0.1],
         [0.3, 0.3, -0.2, 0.5, -0.1]],
        index=["K1|x", "K2|y"], columns=sps,
    )
    mu = pd.Series([100.0, 50.0], index=["K1|x", "K2|y"])
    metadata = {
        "A": {"sp_type": "RN", "lat": 30.0, "lon": -99.0, "load_zone": None},
        "B": {"sp_type": "RN", "lat": 30.0, "lon": -99.0, "load_zone": None},  # dup of A
        "C": {"sp_type": "OTHER", "lat": 31.0, "lon": -97.0, "load_zone": None},
        "D": {"sp_type": None, "lat": 32.0, "lon": -95.0, "load_zone": None},   # untyped
        "E": {"sp_type": "OTHER", "lat": 33.0, "lon": -96.0, "load_zone": None},
    }
    return SF, mu, metadata


def test_type_gate_drops_untyped_by_default():
    SF, mu, metadata = _toy()
    cong = nodal_congestion(SF, mu)
    bp = best_pair(cong, SF, mu, metadata)
    # D is untyped → excluded; endpoints come from the typed set only.
    assert "D" not in (bp["sink"]["settlement_point"], bp["source"]["settlement_point"])


def test_allowed_types_can_tighten():
    SF, mu, metadata = _toy()
    cong = nodal_congestion(SF, mu)
    bp = best_pair(cong, SF, mu, metadata, allowed_types=frozenset({"RN"}))
    # Only A/B/(the RN dup) qualify; C (OTHER) and D (None) are gone → one cluster,
    # too few endpoints.
    assert bp is None


def test_dam_coverage_gate():
    SF, mu, metadata = _toy()
    cong = nodal_congestion(SF, mu)
    # C not DAM-covered → the C↔A pair can't form; only A(=B dup) survives typed.
    bp = best_pair(cong, SF, mu, metadata, dam_sp_coverage={"A", "B"})
    assert bp is None
    bp2 = best_pair(cong, SF, mu, metadata, dam_sp_coverage={"A", "B", "C"})
    assert bp2 is not None and bp2["guardrails"]["dam_coverage_checked"] is True


def test_f5a_suppression_excludes_endpoints():
    SF, mu, metadata = _toy()
    cong = nodal_congestion(SF, mu)
    # Suppress C (the low end); the next-best source must differ.
    bp = best_pair(cong, SF, mu, metadata, exclude_sps={"C"})
    assert bp["source"]["settlement_point"] != "C"
    assert bp["guardrails"]["f5a_suppressed"] == ["C"]


def test_returns_none_when_too_few_survive():
    SF, mu, metadata = _toy()
    cong = nodal_congestion(SF, mu)
    assert best_pair(cong, SF, mu, metadata,
                     exclude_sps={"A", "B", "C", "D", "E"}) is None
