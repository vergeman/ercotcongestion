"""Golden tests for F1/F2/F3 against the real June-30 artifact.

The fixture (``fixtures/june30_he17_full.npz``) carries the whole day's forecast
μ̂ (24×1057) and the precomputed per-constraint reach, so F1's hour-vs-daily
ranks are exact over all 1057 constraints; plus the full SF rows of the HE17
top-10 (which include WESTEX, 107__B, and TREADW) so F2/F3 see the *global*
footprint, not the bounded matrix frame.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/analysis/tests/test_families.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.analysis.families import (
    constraint_node_extrema,
    constraint_stats,
    hour_ranked_constraints,
    split_constraint_key,
)

FIXTURE = Path(__file__).parent / "fixtures" / "june30_he17_full.npz"
HOUR = pd.Timestamp("2026-06-30T21:00:00", tz="UTC")  # HE17 CT

B107 = "107__B|SHC2EXC5"
WESTEX = "WESTEX|BASE CASE"
TREADW = "TREADW_YELWJC1_1|DBIGKEN5"


@pytest.fixture
def day():
    """(reach, E_mu, sample_SF) for 2026-06-30."""
    z = np.load(FIXTURE, allow_pickle=True)
    constraints = [str(c) for c in z["constraints"]]
    hours = pd.DatetimeIndex([pd.Timestamp(h) for h in z["hours"]])
    E_mu = pd.DataFrame(z["e_mu"], index=hours, columns=constraints)
    reach = pd.Series(z["reach"], index=constraints)
    sample_sf = pd.DataFrame(
        z["sample_sf"],
        index=[str(c) for c in z["sample_constraints"]],
        columns=[str(s) for s in z["sp_names"]],
    )
    return reach, E_mu, sample_sf


# --- F1 ---------------------------------------------------------------------

def test_f1_hour_and_daily_ranks_are_distinct(day):
    """The 107__B lesson: hour rank and daily rank are different statements."""
    reach, E_mu, _ = day
    top = hour_ranked_constraints(reach, E_mu, HOUR, top_k=10)
    by_key = {r["constraint_key"]: r for r in top}

    # 107__B is the broadest constraint *this hour* but ranks 2nd all-day;
    # WESTEX is the day's #1 yet only 2nd at HE17.
    assert by_key[B107]["hour_rank"] == 1
    assert by_key[B107]["daily_rank"] == 2
    assert by_key[WESTEX]["hour_rank"] == 2
    assert by_key[WESTEX]["daily_rank"] == 1
    assert by_key[TREADW]["hour_rank"] == 7
    assert by_key[TREADW]["daily_rank"] == 6

    # Footprint magnitudes from the walkthrough.
    assert by_key[B107]["hour_score"] == pytest.approx(3813, abs=2)
    assert by_key[WESTEX]["hour_score"] == pytest.approx(2422, abs=2)
    assert by_key[WESTEX]["daily_score"] == pytest.approx(47438, abs=5)
    assert by_key[B107]["daily_score"] == pytest.approx(32761, abs=5)

    # Output is ordered by hour_score and split into name/contingency.
    assert [r["hour_rank"] for r in top] == list(range(1, 11))
    assert by_key[B107]["constraint_name"] == "107__B"
    assert by_key[B107]["contingency_name"] == "SHC2EXC5"


# --- F2 ---------------------------------------------------------------------

def test_f2_global_extrema_from_full_row(day):
    """F2 surfaces the true peak exposures, not the visible-columns lie."""
    _, E_mu, SF = day
    mu = E_mu.loc[HOUR]

    ext = constraint_node_extrema(SF.loc[B107], mu[B107])
    top_import = ext["import"][0]
    assert top_import["settlement_point"] == "RN_DEC_AGR_B"
    assert top_import["sf"] == pytest.approx(-0.282, abs=0.001)
    assert top_import["contribution"] == pytest.approx(13.25, abs=0.02)
    # Import-side contributions are positive (−SF·μ with SF<0, μ>0).
    assert all(n["contribution"] > 0 for n in ext["import"])
    assert all(n["contribution"] < 0 for n in ext["export"])

    treadw = constraint_node_extrema(SF.loc[TREADW], mu[TREADW])
    assert treadw["import"][0]["settlement_point"] == "JUNCTION_RN"
    assert treadw["import"][0]["contribution"] == pytest.approx(25.91, abs=0.02)
    assert treadw["export"][0]["settlement_point"] == "CFLATS_UNIT"
    assert treadw["export"][0]["contribution"] == pytest.approx(-17.09, abs=0.02)


def test_f2_attaches_metadata_when_present(day):
    """Metadata (type/geocode) is merged per node, None where the SP is absent."""
    _, E_mu, SF = day
    mu = E_mu.loc[HOUR]
    metadata = {"JUNCTION_RN": {"sp_type": "RN", "lat": 30.5, "lon": -99.8}}
    ext = constraint_node_extrema(SF.loc[TREADW], mu[TREADW], metadata=metadata)
    junction = ext["import"][0]
    assert junction["sp_type"] == "RN"
    assert junction["lat"] == 30.5
    # An SP with no metadata entry still returns, with null attributes.
    assert ext["export"][0]["sp_type"] is None


# --- F3 ---------------------------------------------------------------------

def test_f3_broad_vs_separator(day):
    """107__B is broad/one-sided; TREADW is a two-sided strong separator."""
    _, E_mu, SF = day
    mu = E_mu.loc[HOUR]

    broad = constraint_stats(SF.loc[B107], mu[B107])
    assert broad["import_count"] > 50 * broad["export_count"]   # overwhelmingly one-sided
    assert broad["top5_share"] < 0.05                           # no dominant cell
    assert broad["peak_abs_sf"] == pytest.approx(0.282, abs=0.001)
    assert broad["max_contrast"]["value"] == pytest.approx(17.30, abs=0.02)
    assert broad["max_contrast"]["export_sp"] == "WCPP_CC1"
    assert broad["max_contrast"]["import_sp"] == "RN_DEC_AGR_B"

    sep = constraint_stats(SF.loc[TREADW], mu[TREADW])
    assert sep["import_count"] > 0 and sep["export_count"] > 0   # two-sided
    assert sep["reach"] < broad["reach"]                        # localized
    assert sep["max_contrast"]["value"] == pytest.approx(43.00, abs=0.02)
    assert {sep["max_contrast"]["export_sp"], sep["max_contrast"]["import_sp"]} == {
        "CFLATS_UNIT", "JUNCTION_RN"}


def test_split_constraint_key():
    assert split_constraint_key("107__B|SHC2EXC5") == ("107__B", "SHC2EXC5")
    assert split_constraint_key("NOBAR") == ("NOBAR", None)
