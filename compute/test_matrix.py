"""Unit tests for the Phase 4 additions to `compute.matrix`.

Covers `_by_regime`, `_sign_agreement`, and `_threshold_counts` on
synthetic 8-zone × N-hour inputs.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \
        /compute/test_matrix.py -v
"""
import numpy as np
import pandas as pd

from compute.matrix import (
    _by_regime,
    _regime_of,
    _regime_split_apply,
    _sign_agreement,
    _split_columns_by_regime,
    _threshold_counts,
)

ZONES = [
    "coast", "east", "far_west", "north",
    "north_central", "south_central", "southern", "west",
]


def _hours(regime: str, n: int, base: str = "2025-06-01T00:00:00+00:00") -> list[str]:
    base_ts = pd.Timestamp(base)
    return [f"{regime}|{(base_ts + pd.Timedelta(hours=i)).isoformat()}" for i in range(n)]


def _make_matrix(cols: list[str], values: np.ndarray) -> pd.DataFrame:
    assert values.shape == (len(ZONES), len(cols))
    return pd.DataFrame(values, index=ZONES, columns=cols)


# ---------------------------------------------------------------------------
# _regime_of / _split_columns_by_regime
# ---------------------------------------------------------------------------

def test_regime_of_and_split():
    cols = _hours("summer_peak", 3) + _hours("winter_peak", 2)
    assert _regime_of(cols[0]) == "summer_peak"
    assert _regime_of("no_delim") == ""
    groups = _split_columns_by_regime(cols)
    assert list(groups) == ["summer_peak", "winter_peak"]
    assert len(groups["summer_peak"]) == 3
    assert len(groups["winter_peak"]) == 2


# ---------------------------------------------------------------------------
# _by_regime — Spearman ρ aggregation
# ---------------------------------------------------------------------------

def test_by_regime_aggregates_rho_by_regime():
    per_hour = [
        {"hour": "summer_peak|t1", "rho": 0.5},
        {"hour": "summer_peak|t2", "rho": -0.1},
        {"hour": "summer_peak|t3", "rho": 0.3},
        {"hour": "winter_peak|t1", "rho": 0.9},
        {"hour": "winter_peak|t2", "rho": None},
    ]
    out = _by_regime(per_hour)
    assert set(out) == {"summer_peak", "winter_peak"}
    assert out["summer_peak"]["n"] == 3
    assert out["summer_peak"]["mean"] == pytest_approx(np.mean([0.5, -0.1, 0.3]))
    assert out["summer_peak"]["frac_positive"] == pytest_approx(2 / 3)
    assert out["winter_peak"]["n"] == 1
    assert out["winter_peak"]["mean"] == 0.9
    assert out["winter_peak"]["frac_positive"] == 1.0


def test_by_regime_empty_input():
    assert _by_regime([]) == {}


# ---------------------------------------------------------------------------
# _sign_agreement
# ---------------------------------------------------------------------------

def test_sign_agreement_perfect_and_none():
    cols = _hours("summer_peak", 4)
    values = np.array([
        [1, 1, -1, -1],   # coast: sign flips per hour
    ] + [[0.0] * 4] * 7)  # other zones flat 0
    Z_m = _make_matrix(cols, values.astype(float))
    Z_e = Z_m.copy()  # identical → 100% agreement everywhere
    out = _sign_agreement(Z_m, Z_e, ZONES)
    assert out["overall"]["frac_agree"] == 1.0
    for z in ZONES:
        assert out["per_key"][z]["frac_agree"] == 1.0

    # Flip ERCOT sign on coast → 0% agreement on coast, still 100% elsewhere
    Z_e2 = Z_e.copy()
    Z_e2.loc["coast"] = -Z_e2.loc["coast"]
    out2 = _sign_agreement(Z_m, Z_e2, ZONES)
    assert out2["per_key"]["coast"]["frac_agree"] == 0.0
    assert out2["per_key"]["east"]["frac_agree"] == 1.0
    # 4/32 hours flipped
    assert out2["overall"]["frac_agree"] == pytest_approx(28 / 32)


def test_sign_agreement_handles_nan():
    cols = _hours("summer_peak", 4)
    v = np.zeros((8, 4))
    v[0] = [1.0, np.nan, -1.0, 1.0]
    Z_m = _make_matrix(cols, v)
    Z_e = Z_m.copy()
    out = _sign_agreement(Z_m, Z_e, ZONES)
    # coast: 3 valid hours (1 NaN dropped), all agree
    assert out["per_key"]["coast"]["n"] == 3
    assert out["per_key"]["coast"]["frac_agree"] == 1.0


def test_sign_agreement_empty_returns_none():
    empty = pd.DataFrame(index=ZONES)
    out = _sign_agreement(empty, empty, ZONES)
    assert out["overall"] is None
    assert out["per_key"] == {}


# ---------------------------------------------------------------------------
# _threshold_counts
# ---------------------------------------------------------------------------

def test_threshold_counts_fractions():
    cols = _hours("summer_peak", 10)
    v = np.zeros((8, 10))
    # coast: absolute values 1..10 → for τ=5, 5/10 hours exceed; for τ=20, 0/10
    v[0] = np.arange(1, 11, dtype=float)
    Z = _make_matrix(cols, v)
    out = _threshold_counts(Z, ZONES, (5.0, 20.0))
    assert out["thresholds"] == [5.0, 20.0]
    assert out["per_key"]["coast"]["fractions"]["5.0"] == pytest_approx(5 / 10)
    assert out["per_key"]["coast"]["fractions"]["20.0"] == 0.0
    # zones with all-zero rows: 0 exceed either threshold
    assert out["per_key"]["east"]["fractions"]["5.0"] == 0.0


def test_threshold_counts_all_nan_key():
    cols = _hours("summer_peak", 3)
    v = np.zeros((8, 3))
    v[0] = np.nan
    Z = _make_matrix(cols, v)
    out = _threshold_counts(Z, ZONES, (5.0,))
    assert out["per_key"]["coast"]["n"] == 0
    assert out["per_key"]["coast"]["fractions"]["5.0"] is None


# ---------------------------------------------------------------------------
# _regime_split_apply — end-to-end wiring check
# ---------------------------------------------------------------------------

def test_regime_split_apply_partitions_columns():
    cols = _hours("summer_peak", 3) + _hours("winter_peak", 2)
    v = np.zeros((8, 5))
    v[0] = [10, 10, 10, 1, 1]  # coast: exceeds τ=5 in all summer, none in winter
    Z = _make_matrix(cols, v)
    out = _regime_split_apply(
        Z, None,
        lambda m: _threshold_counts(m, ZONES, (5.0,)),
    )
    assert set(out) == {"summer_peak", "winter_peak"}
    assert out["summer_peak"]["per_key"]["coast"]["fractions"]["5.0"] == 1.0
    assert out["winter_peak"]["per_key"]["coast"]["fractions"]["5.0"] == 0.0


# ---------------------------------------------------------------------------
# Local approx helper — avoids importing pytest.approx in module scope
# so this file also imports cleanly under bare unittest.
# ---------------------------------------------------------------------------

class pytest_approx:
    def __init__(self, expected, rel=1e-9, abs=1e-9):
        self.expected = float(expected)
        self.rel = rel
        self.abs = abs

    def __eq__(self, other):
        return abs(float(other) - self.expected) <= max(
            self.abs, self.rel * abs(self.expected)
        )

    def __repr__(self):
        return f"approx({self.expected})"
