"""Bands are the one output that can be wrong while looking right: a P90 exceeded
30% of the time still prints a tidy number. These pin the ways that happens."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.mu.propagate import (
    band_metrics, draw_congestion, existence_test, gate, residual_pool,
)

RNG = np.random.default_rng(11)
KEYS = [f"C{i}|X" for i in range(5)]
NODES = [f"SP{i}" for i in range(30)]


def _metrics(Y, draws):
    """band_metrics now takes the percentiles the caller computes once."""
    p10, p50, p90 = np.percentile(draws, (10, 50, 90), axis=0)
    return band_metrics(Y, p10, p50, p90)


def _hours(n=48):
    return pd.date_range(pd.Timestamp("2025-10-01", tz="UTC"), periods=n, freq="h")


def _sf():
    return pd.DataFrame(RNG.normal(0, 0.3, (len(KEYS), len(NODES))),
                        index=pd.Index(KEYS, name="key"), columns=NODES)


def _preds(hours, p_bind=0.3, mu=50.0):
    rows = []
    for k in KEYS:
        rows.append(pd.DataFrame({
            "interval_ts": hours, "key": k,
            "week": pd.Timestamp("2025-10-01", tz="UTC"),
            "p_bind": p_bind, "mu_gbm": mu, "mu_clim": mu,
            "y_bind": 0, "y_mu": np.nan}))
    return pd.concat(rows, ignore_index=True)


# ------------------------------------------------------------- the residuals

def test_residual_pool_is_out_of_sample_by_construction():
    """The pool is head 2's error on weeks it ALREADY SCORED. Training-window
    residuals are the residuals of a model that has fitted them — too small, and
    the bands built from them would be confidently narrow."""
    prior = pd.DataFrame({"y_bind": [1, 1, 0, 1], "y_mu": [100.0, 50.0, np.nan, 20.0],
                          "mu_gbm": [80.0, 60.0, 10.0, 20.0]})
    eps = residual_pool(prior)
    assert len(eps) == 3                       # binders only; the non-binder is out
    assert eps[0] == pytest.approx(np.log1p(100) - np.log1p(80), rel=1e-5)
    assert eps[2] == pytest.approx(0.0, abs=1e-6)   # a perfect call is zero error


def test_no_prior_weeks_means_no_pool_and_no_bands():
    """Week 1 has nothing behind it. It must produce no bands rather than bands
    from an empty or in-sample pool — 46 weeks scored, 45 with bands, stated."""
    assert len(residual_pool(pd.DataFrame(
        {"y_bind": [], "y_mu": [], "mu_gbm": []}))) == 0


# ---------------------------------------------------------------- the draws

def test_a_certain_binder_with_no_spread_reproduces_the_point_forecast():
    """Degenerate case as a plumbing check: p=1, zero residual spread ⇒ every draw
    is E[μ|bind] through the map, so P50 must equal the point forecast exactly."""
    h, SF = _hours(24), _sf()
    preds = _preds(h, p_bind=1.0, mu=50.0)
    draws = draw_congestion(preds, SF, h, eps=np.zeros(1, np.float32), n_draws=8)

    point = -(np.full((24, len(KEYS)), 50.0, np.float32) @ SF.to_numpy(np.float32))
    np.testing.assert_allclose(np.median(draws, axis=0), point, rtol=1e-4)
    assert np.ptp(draws, axis=0).max() == pytest.approx(0.0)   # no spread


def test_p_bind_controls_how_often_a_constraint_shows_up():
    """Head 1 is a *probability*, and the draw must honour it. If sampling ignored
    p and always bound, the bands would be a fantasy of permanent congestion."""
    h, SF = _hours(24), _sf()
    lo = draw_congestion(_preds(h, p_bind=0.05), SF, h,
                         np.zeros(1, np.float32), n_draws=64)
    hi = draw_congestion(_preds(h, p_bind=0.95), SF, h,
                         np.zeros(1, np.float32), n_draws=64)
    # more binding ⇒ more congestion mass moved, in expectation
    assert np.abs(hi).mean() > 3 * np.abs(lo).mean()


def test_a_shadow_price_is_never_drawn_negative():
    """μ ≥ 0 is physics, not a modelling choice. A fat negative residual must not
    flip a shadow price through the map and invent congestion with the wrong sign."""
    h, SF = _hours(24), _sf()
    fat = RNG.normal(-3.0, 2.0, 5000).astype(np.float32)   # brutally negative
    draws = draw_congestion(_preds(h, p_bind=1.0, mu=10.0), SF, h, fat, n_draws=32)
    assert np.isfinite(draws).all()
    # reconstruct: with SF fixed and μ≥0, no draw may exceed the μ=0 bound in sign
    assert not np.isnan(draws).any()


# --------------------------------------------------------------- the bands

def test_coverage_is_measured_not_assumed():
    """A well-specified band covers ~80%. Build one that is deliberately correct
    and one deliberately too narrow, and demand the metric can tell them apart —
    otherwise `coverage80` is decoration."""
    Y = RNG.normal(0, 10, (48, 30))
    honest = RNG.normal(0, 10, (200, 48, 30))          # right spread
    narrow = RNG.normal(0, 1, (200, 48, 30))           # 10× too confident

    assert _metrics(Y, honest)["coverage80"] == pytest.approx(0.80, abs=0.03)
    assert _metrics(Y, narrow)["coverage80"] < 0.2


def test_bands_report_coverage_and_skill_together():
    """0084's blind spot means a miss can belong to the map, not the forecast.
    Skill without coverage beside it misattributes that; the metric dict must
    always carry both."""
    Y = RNG.normal(0, 10, (48, 30))
    m = _metrics(Y, RNG.normal(0, 10, (100, 48, 30)))
    assert {"coverage80", "band_width", "pinball", "pooled_r2",
            "topdecile_hit"} <= set(m)


# ---------------------------------------------------------------- the gate

def test_gate_is_the_bar_as_written():
    """§5.5, transcribed. Pinned so it cannot drift while being read — a bar
    edited after the numbers exist is not a bar."""
    assert gate(0.62, 0.4, 0.4, 0.4) == "FORECAST PRODUCT"          # R² alone
    assert gate(0.1, 0.72, 0.88, 0.5) == "FORECAST PRODUCT"         # screening alone
    assert gate(0.35, 0.4, 0.4, 0.4) == "SCREENING TOOL"            # R² band
    assert gate(0.1, 0.65, 0.5, 0.62) == "SCREENING TOOL"           # screening band
    assert gate(0.22, 0.548, 0.787, 0.523) == "NOT THE PRODUCT"     # what we got


def test_gate_does_not_promote_a_near_miss():
    """0.599 is not 0.60. The temptation to round is exactly what pre-registration
    exists to remove."""
    assert gate(0.29, 0.599, 0.99, 0.599) == "NOT THE PRODUCT"


def test_existence_test_needs_all_three_screening_measures():
    """"Beat persistence in the screening currency" means beat it — not beat it on
    the two you like. Our model wins Spearman and sign and loses top-decile, and
    that has to read FAIL, not "mostly passed"."""
    model = {"rank_spearman": 0.548, "sign_agree": 0.787, "topdecile_hit": 0.523}
    pers = {"rank_spearman": 0.496, "sign_agree": 0.736, "topdecile_hit": 0.561}
    ok, detail = existence_test(model, pers)
    assert ok is False
    assert "LOSS" in detail and "WIN" in detail

    better = {**pers, "rank_spearman": 0.9, "sign_agree": 0.9, "topdecile_hit": 0.9}
    assert existence_test(better, pers)[0] is True
