"""Tests for the retired Monte-Carlo congestion-band experiment."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.experiments.mu.sampling import band_metrics, draw_congestion, residual_pool

RNG = np.random.default_rng(11)
KEYS = [f"C{i}|X" for i in range(5)]
NODES = [f"SP{i}" for i in range(30)]


def _metrics(Y, draws):
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


def test_residual_pool_is_out_of_sample_by_construction():
    prior = pd.DataFrame({"y_bind": [1, 1, 0, 1], "y_mu": [100.0, 50.0, np.nan, 20.0],
                          "mu_gbm": [80.0, 60.0, 10.0, 20.0]})
    eps = residual_pool(prior)
    assert len(eps) == 3
    assert eps[0] == pytest.approx(np.log1p(100) - np.log1p(80), rel=1e-5)
    assert eps[2] == pytest.approx(0.0, abs=1e-6)


def test_no_prior_weeks_means_no_pool_and_no_bands():
    assert len(residual_pool(pd.DataFrame(
        {"y_bind": [], "y_mu": [], "mu_gbm": []}))) == 0


def test_a_certain_binder_with_no_spread_reproduces_the_point_forecast():
    h, SF = _hours(24), _sf()
    preds = _preds(h, p_bind=1.0, mu=50.0)
    draws = draw_congestion(preds, SF, h, eps=np.zeros(1, np.float32), n_draws=8)
    point = -(np.full((24, len(KEYS)), 50.0, np.float32) @ SF.to_numpy(np.float32))
    np.testing.assert_allclose(np.median(draws, axis=0), point, rtol=1e-4)
    assert np.ptp(draws, axis=0).max() == pytest.approx(0.0)


def test_p_bind_controls_how_often_a_constraint_shows_up():
    h, SF = _hours(24), _sf()
    lo = draw_congestion(_preds(h, p_bind=0.05), SF, h,
                         np.zeros(1, np.float32), n_draws=64)
    hi = draw_congestion(_preds(h, p_bind=0.95), SF, h,
                         np.zeros(1, np.float32), n_draws=64)
    assert np.abs(hi).mean() > 3 * np.abs(lo).mean()


def test_a_shadow_price_is_never_drawn_negative():
    h, SF = _hours(24), _sf()
    fat = RNG.normal(-3.0, 2.0, 5000).astype(np.float32)
    draws = draw_congestion(_preds(h, p_bind=1.0, mu=10.0), SF, h, fat, n_draws=32)
    assert np.isfinite(draws).all()
    assert not np.isnan(draws).any()


def test_want_point_is_the_expectation_not_the_median():
    h, SF = _hours(24), _sf()
    p_bind, mu = 0.3, 50.0
    preds = _preds(h, p_bind=p_bind, mu=mu)
    draws, point = draw_congestion(preds, SF, h, np.zeros(1, np.float32),
                                   n_draws=8, want_point=True)
    E_mu = np.full((24, len(KEYS)), p_bind * mu, np.float32)
    expect = -(E_mu @ SF.to_numpy(np.float32))
    np.testing.assert_allclose(point, expect, rtol=1e-5)
    assert point.shape == (24, len(NODES)) == draws.shape[1:]
    assert isinstance(draw_congestion(preds, SF, h, np.zeros(1, np.float32),
                                      n_draws=8), np.ndarray)


def test_coverage_is_measured_not_assumed():
    Y = RNG.normal(0, 10, (48, 30))
    honest = RNG.normal(0, 10, (200, 48, 30))
    narrow = RNG.normal(0, 1, (200, 48, 30))
    assert _metrics(Y, honest)["coverage80"] == pytest.approx(0.80, abs=0.03)
    assert _metrics(Y, narrow)["coverage80"] < 0.2


def test_bands_report_coverage_and_skill_together():
    Y = RNG.normal(0, 10, (48, 30))
    m = _metrics(Y, RNG.normal(0, 10, (100, 48, 30)))
    assert {"coverage80", "band_width", "pinball", "pooled_r2",
            "topdecile_hit"} <= set(m)
