"""Golden test: the brief primitives must reproduce the hand-computed June-30
numbers from docs/last_mile.md before any narrative or persistence wraps them.

The fixture (``fixtures/june30_he17.npz``) is a compact slice of the real
``mu-all-v1`` artifact for delivery day 2026-06-30 at HE17 (16:00 CT / 21:00
UTC): the full forecast-μ vector over 1057 constraints plus the SF columns of
the four endpoints the walkthrough separated. That is everything the pure
formulas need — ``cong[sp]`` depends only on that SP's column — so the two
golden separations and their dominant drivers are pinned exactly, hermetically,
with no live DB.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/analysis/tests/test_brief.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.analysis.brief import nodal_congestion, pair_contributions

FIXTURE = Path(__file__).parent / "fixtures" / "june30_he17.npz"


@pytest.fixture
def june30_he17():
    """(SF, mu) for the four golden endpoints at 2026-06-30 HE17."""
    z = np.load(FIXTURE, allow_pickle=True)
    constraints = [str(c) for c in z["constraints"]]
    sp_names = [str(s) for s in z["sp_names"]]
    mu = pd.Series(z["mu"], index=constraints)
    SF = pd.DataFrame(z["sf"], index=constraints, columns=sp_names)
    return SF, mu


def test_olney_lgw_separation(june30_he17):
    """OLNEY − LGW = $159.19, with two 6830 constraints as the top drivers."""
    SF, mu = june30_he17
    cong = nodal_congestion(SF, mu)
    spread = cong["OLNEYTN_AGR1"] - cong["LGW_UNIT_ALL"]
    assert spread == pytest.approx(159.19, abs=0.01)

    drivers = pair_contributions(SF, mu, sink="OLNEYTN_AGR1", source="LGW_UNIT_ALL")
    # Drivers reconcile exactly to the spread.
    assert drivers.sum() == pytest.approx(spread, abs=0.01)
    top = drivers.reindex(drivers.abs().sort_values(ascending=False).index)
    assert top.index[0] == "6830__B|SGRMGRS8"
    assert top.iloc[0] == pytest.approx(74.36, abs=0.01)
    assert top.index[1] == "6830__B|DGRMGRS8"
    assert top.iloc[1] == pytest.approx(42.07, abs=0.01)


def test_junction_cflats_separation(june30_he17):
    """JUNCTION − CFLATS = $69.10, dominated by the TREADW separator ($43.00)."""
    SF, mu = june30_he17
    cong = nodal_congestion(SF, mu)
    spread = cong["JUNCTION_RN"] - cong["CFLATS_UNIT"]
    assert spread == pytest.approx(69.10, abs=0.01)

    drivers = pair_contributions(SF, mu, sink="JUNCTION_RN", source="CFLATS_UNIT")
    assert drivers.sum() == pytest.approx(spread, abs=0.01)
    top = drivers.reindex(drivers.abs().sort_values(ascending=False).index)
    assert top.index[0] == "TREADW_YELWJC1_1|DBIGKEN5"
    assert top.iloc[0] == pytest.approx(43.00, abs=0.01)


def test_pair_terms_reconcile_to_endpoints_at_float64_precision():
    """Dense float32 SF artifacts must not lose reconciliation in reduction order."""
    rng = np.random.default_rng(7)
    SF = pd.DataFrame(rng.normal(size=(1024, 2)).astype("float32"), columns=["SOURCE", "SINK"])
    mu = pd.Series(rng.uniform(0, 10_000, size=1024), index=SF.index)

    congestion = nodal_congestion(SF, mu)
    drivers = pair_contributions(SF, mu, sink="SINK", source="SOURCE")
    assert drivers.sum() == pytest.approx(congestion["SINK"] - congestion["SOURCE"], abs=1e-9)
