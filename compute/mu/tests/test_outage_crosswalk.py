"""NP1-346 authoritative crosswalk (plan/0089 commit 1).

The two acceptance criteria that live at commit 1, and the second is the one the whole
plan turns on:

  * *The crosswalk is AUTHORITATIVE* — a unit code resolves through ERCOT's
    `Resource_Node_to_Unit` registry to its real settlement point, **not** by splitting
    the code on underscores (the probe's 55.8% heuristic, which this replaces).
  * *Coverage is reported by outage MW, never row count* — a crosswalk that reaches most
    rows but only the tiny derates is a kill, and the number has to say so.
"""
from __future__ import annotations

import pandas as pd
import pytest

from compute.mu.outage_crosswalk import (Crosswalk, coverage, load_crosswalk,
                                         verdict)


@pytest.fixture
def registry_dir(tmp_path):
    """A minimal but faithful copy of the two registries, with the real column names.

    `B_DAVIS_B_DAVIG1` is the plan's own example of why underscore-splitting fails: naive
    code would derive station `B`, but the registry says the unit belongs to settlement
    point `B_DAVIS_RN`. `SHARED` is a substation carrying two settlement points — the
    ambiguity the fallback must refuse rather than guess.
    """
    pd.DataFrame({
        "RESOURCE_NODE":   ["B_DAVIS_RN", "CALAVERS_RN", "SHARED_RN1", "SHARED_RN2"],
        "UNIT_SUBSTATION": ["B_DAVIS",    "CALAVERS",    "SHARED",     "SHARED"],
        "UNIT_NAME":       ["B_DAVIG1",   "OWS2",        "G1",         "G2"],
    }).to_csv(tmp_path / "Resource_Node_to_Unit_20260101.csv", index=False)

    pd.DataFrame({
        "SUBSTATION":    ["B_DAVIS", "CALAVERS", "SHARED",     "SHARED",     "SOLOSUB"],
        "RESOURCE_NODE": ["B_DAVIS_RN", "CALAVERS_RN", "SHARED_RN1", "SHARED_RN2", "SOLO_RN"],
    }).to_csv(tmp_path / "Settlement_Points_20260101.csv", index=False)
    return tmp_path


@pytest.fixture
def universe():
    return {"B_DAVIS_RN", "CALAVERS_RN", "SHARED_RN1", "SHARED_RN2", "SOLO_RN"}


def test_crosswalk_is_authoritative_not_underscore_split(registry_dir, universe):
    """The plan's example: the registry, not the underscores, decides the SP."""
    x = load_crosswalk(registry_dir)
    sp, method = x.locate("B_DAVIS_B_DAVIG1", "B_DAVIS", universe)
    assert (sp, method) == ("B_DAVIS_RN", "unitcode")
    # And it is NOT the naive station `B` the probe's prefix heuristic would have taken.
    assert sp != "B"


def test_resource_name_that_is_itself_a_settlement_point(registry_dir):
    x = load_crosswalk(registry_dir)
    # Unit code unknown, but the resource name is a priced SP in its own right.
    sp, method = x.locate("UNKNOWN_UNIT", "SOLO_RN", {"SOLO_RN"})
    assert (sp, method) == ("SOLO_RN", "resname_sp")


def test_ambiguous_substation_is_refused_not_guessed(registry_dir, universe):
    """`SHARED` carries two settlement points — the fallback must decline it."""
    x = load_crosswalk(registry_dir)
    assert "SHARED" not in x.substation_to_sp
    sp, method = x.locate("SHARED_UNKNOWNUNIT", "SHARED", universe)
    assert sp is None and method is None


def test_registry_hit_outside_the_sf_universe_is_not_locatable(registry_dir):
    """A unit that resolves in the registry but whose SP the SF map never prices has
    nowhere to place its MW — it is unlocated, not a silent pass."""
    x = load_crosswalk(registry_dir)
    sp, method = x.locate("B_DAVIS_B_DAVIG1", "B_DAVIS", sp_universe={"CALAVERS_RN"})
    assert sp is None


def test_coverage_is_weighted_by_mw_not_row_count(universe):
    """One 1-MW row locates, one 999-MW row does not: 50% of rows, but the number that
    governs the gate must reflect the MW — a near-kill, not a pass."""
    x = Crosswalk(unitcode_to_sp={"CALAVERS_OWS2": "CALAVERS_RN"},
                  substation_to_sp={}, sp_registry=set())
    df = pd.DataFrame({
        "Resource Name":      ["CALAVERS", "GHOST"],
        "Resource Unit Code": ["CALAVERS_OWS2", "GHOST_G1"],
        MW_COL:               [1.0, 999.0],
    })
    rep = coverage(df, x, universe, mw_col=MW_COL)
    assert rep["row_rate"] == pytest.approx(0.5)
    assert rep["rate"] == pytest.approx(1.0 / 1000.0)
    assert rep["unlocated"].loc["GHOST"] == pytest.approx(999.0)


def test_verdict_reads_the_pre_registered_bars():
    assert verdict(0.75)[0] == "BUILD"
    assert verdict(0.45)[0] == "BUILD (flagged subset)"
    assert verdict(0.20)[0] == "DEAD"


MW_COL = "Effective MW Reduction Due to Outage"
