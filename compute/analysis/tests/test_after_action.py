"""Golden tests for F6 — after-action at 2026-06-30 HE17.

The fixture (``fixtures/june30_he17_f6.npz``) holds the pieces the pure F6
functions consume: reach + forecast/realized μ over all 1057 constraints (for the
ranking scorecard) and, for five endpoints, their forecast/reconstruction/realized
congestion plus P10/P90 bands (for the decomposition and hub triple). It pins the
documented OLNEY−LGW after-action story: $159.19 forecast → $250.08 reconstruction
→ $237.40 actual.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/analysis/tests/test_after_action.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.analysis.after_action import (
    dam_match_coverage,
    hub_triples,
    scorecard,
    spread_decomposition,
)

FIXTURE = Path(__file__).parent / "fixtures" / "june30_he17_f6.npz"


@pytest.fixture
def f6():
    z = np.load(FIXTURE, allow_pickle=True)
    constraints = [str(c) for c in z["constraints"]]
    ep = [str(s) for s in z["ep"]]
    return {
        "reach": pd.Series(z["reach"], index=constraints),
        "mu_fc": pd.Series(z["mu_fc"], index=constraints),
        "mu_dam": pd.Series(z["mu_dam"], index=constraints),
        "dam_keys": [str(k) for k in z["dam_keys"]],
        "cong_fc": pd.Series(z["cong_fc"], index=ep),
        "cong_recon": pd.Series(z["cong_recon"], index=ep),
        "realized": pd.Series(z["realized"], index=ep),
        "p10": pd.Series(z["p10"], index=ep),
        "p90": pd.Series(z["p90"], index=ep),
    }


def test_spread_decomposition_olney_lgw(f6):
    """The headline June-30 story reconciles severity vs reconstruction error."""
    d = spread_decomposition(f6["cong_fc"], f6["cong_recon"], f6["realized"],
                             "OLNEYTN_AGR1", "LGW_UNIT_ALL")
    assert d["forecast_spread"] == pytest.approx(159.19, abs=0.02)
    assert d["recon_spread"] == pytest.approx(250.08, abs=0.02)
    assert d["actual_spread"] == pytest.approx(237.40, abs=0.02)
    # The four terms reconcile exactly.
    assert d["forecast_spread"] + d["delta_mu"] == pytest.approx(d["recon_spread"], abs=1e-4)
    assert (d["recon_spread"] + d["spatial_residual"]
            == pytest.approx(d["actual_spread"], abs=1e-4))
    # Severity was underforecast (Δμ large +), reconstruction close (small residual).
    assert d["delta_mu"] == pytest.approx(90.89, abs=0.02)
    assert d["spatial_residual"] == pytest.approx(-12.68, abs=0.02)


def test_spread_decomposition_without_realized(f6):
    """No realized SPP for an endpoint → recon stands, actual/residual are None."""
    d = spread_decomposition(f6["cong_fc"], f6["cong_recon"], None,
                             "OLNEYTN_AGR1", "LGW_UNIT_ALL")
    assert d["recon_spread"] == pytest.approx(250.08, abs=0.02)
    assert d["actual_spread"] is None and d["spatial_residual"] is None


def test_ranking_scorecard(f6):
    """Predicted vs realized HE17 constraint ranking, with miss/alarm exemplars."""
    card = scorecard(f6["mu_fc"].abs() * f6["reach"],
                     f6["mu_dam"].abs() * f6["reach"], top_k=10)
    assert card["recall_at_k"] == pytest.approx(0.8)
    assert card["exact_hits"] == 2

    top = card["predicted"][0]
    assert top["constraint_key"] == "107__B|SHC2EXC5"
    assert (top["predicted_rank"], top["realized_rank"]) == (1, 6)

    # Model underranked the constraint DAM actually pushed; over-ranked another.
    assert card["biggest_severity_miss"]["constraint_key"] == "6830__B|SGRMGRS8"
    assert card["biggest_severity_miss"]["predicted_rank"] > \
        card["biggest_severity_miss"]["realized_rank"]
    assert card["biggest_false_alarm"]["constraint_key"] == "651__B|SCMNCPS5"
    assert card["biggest_false_alarm"]["realized_rank"] > \
        card["biggest_false_alarm"]["predicted_rank"]


def test_hub_triples_band_check(f6):
    triples = {t["settlement_point"]: t
               for t in hub_triples(f6["cong_fc"], f6["cong_recon"], f6["realized"],
                                    f6["p10"], f6["p90"], ["HB_PAN", "LZ_HOUSTON", "HB_WEST"])}
    pan = triples["HB_PAN"]
    assert pan["forecast"] == pytest.approx(-18.09, abs=0.02)
    assert pan["realized"] == pytest.approx(-26.30, abs=0.02)
    # Realized fell inside the forecast P10–P90 band at every hub.
    assert all(t["in_band"] for t in triples.values())


def test_dam_match_coverage(f6):
    # Coverage counts forecast |μ| mass on constraints the DAM feed carries.
    dam_row = f6["mu_dam"].reindex(f6["dam_keys"])
    assert dam_match_coverage(f6["mu_fc"], dam_row) == pytest.approx(0.8546, abs=0.001)


def test_coverage_uses_matched_keys_only():
    mu_fc = pd.Series([30.0, 10.0], index=["A|x", "B|y"])
    dam_row = pd.Series([5.0], index=["A|x"])   # DAM never carries B|y
    assert dam_match_coverage(mu_fc, dam_row) == pytest.approx(0.75)
