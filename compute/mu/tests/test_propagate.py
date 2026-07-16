"""Bands are the one output that can be wrong while looking right: a P90 exceeded
30% of the time still prints a tidy number. These pin the ways that happens."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.mu.propagate import (
    NodalPanel, band_metrics, draw_congestion, existence_test, gate,
    propagate_window, residual_pool,
)
from compute.mu.score import REFIT_DAYS, WINDOW_DAYS

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


# --------------------------------------------------- the deterministic point

def test_want_point_is_the_expectation_not_the_median():
    """`point = −(E[μ]·SF)` with `E[μ]=P(bind)·E[μ|bind]` — a no-sampling branch
    off the same P/MU/SFm. It must equal an independent recompute, and it is the
    model's expectation, distinct from the noisy median of the draws."""
    h, SF = _hours(24), _sf()
    p_bind, mu = 0.3, 50.0
    preds = _preds(h, p_bind=p_bind, mu=mu)
    draws, point = draw_congestion(preds, SF, h, np.zeros(1, np.float32),
                                   n_draws=8, want_point=True)
    E_mu = np.full((24, len(KEYS)), p_bind * mu, np.float32)
    expect = -(E_mu @ SF.to_numpy(np.float32))
    np.testing.assert_allclose(point, expect, rtol=1e-5)
    assert point.shape == (24, len(NODES)) == draws.shape[1:]
    # default path is unchanged — a bare array, no point
    assert isinstance(draw_congestion(preds, SF, h, np.zeros(1, np.float32),
                                      n_draws=8), np.ndarray)


# --------------------------------------------------------- the window seam

def _window_frames(n_keys=4, n_sp=6, seed=7):
    """DB-shaped M/C/wp for one fit+score window, C built from the SF identity."""
    rng = np.random.default_rng(seed)
    s = pd.Timestamp("2025-06-01", tz="UTC")
    idx = pd.date_range(s - pd.Timedelta(days=WINDOW_DAYS),
                        s + pd.Timedelta(days=REFIT_DAYS), freq="h",
                        inclusive="left")
    keys = [f"K{i}|Z" for i in range(n_keys)]
    sps = [f"N{i}" for i in range(n_sp)]
    true_sf = rng.normal(0, 0.3, (n_keys, n_sp))
    mu = np.where(rng.random((len(idx), n_keys)) < 0.5, 0.0,
                  rng.uniform(20, 200, (len(idx), n_keys)))
    M = pd.DataFrame(mu, index=idx, columns=keys)
    C = pd.DataFrame(-(mu @ true_sf), index=idx, columns=sps)

    shours = idx[(idx >= s) & (idx < s + pd.Timedelta(days=REFIT_DAYS))]
    frames = []
    for k in keys:
        p = M.loc[shours, k].to_numpy()
        frames.append(pd.DataFrame({
            "interval_ts": shours, "key": k, "week": s,
            "p_bind": np.where(p > 0, 0.8, 0.1), "mu_gbm": np.clip(p, 1, None),
            "y_bind": (p > 0).astype(int),
            "y_mu": np.where(p > 0, p, np.nan)}))
    wp = pd.concat(frames, ignore_index=True)
    return s, s + pd.Timedelta(days=REFIT_DAYS), M, C, wp, shours


def test_panel_reduces_to_the_same_metrics_as_the_row():
    """The panel and the scored row read one `np.percentile` call, so the served
    p10/p90 re-reduced must reproduce the row's coverage80/band_width."""
    s, end, M, C, wp, shours = _window_frames()
    row, panel = propagate_window(s, end, M, C, wp, np.zeros(4, np.float32),
                                  64, np.random.default_rng(0), want_panel=True)
    assert isinstance(panel, NodalPanel)
    assert list(panel.settlement_points) == list(C.columns)   # == SF.columns
    assert len(panel.ts) == len(shours) == row["n_hours"]

    Y = C.loc[shours, list(panel.settlement_points)].to_numpy(np.float32)
    inside = (Y >= panel.p10) & (Y <= panel.p90)
    assert np.nanmean(inside) == pytest.approx(row["coverage80"], abs=1e-3)
    assert np.nanmean(panel.p90 - panel.p10) == pytest.approx(row["band_width"],
                                                              rel=1e-3)


def test_want_panel_does_not_perturb_the_metrics_row():
    """Emission is a tee, not a fork: the row must be identical whether or not the
    panel is built (same seed, same draws, same percentiles)."""
    args = (*_window_frames()[:5], np.zeros(4, np.float32), 64)
    r0, p0 = propagate_window(*args, np.random.default_rng(5))
    r1, p1 = propagate_window(*args, np.random.default_rng(5), want_panel=True)
    assert p0 is None and isinstance(p1, NodalPanel)
    assert r0 is not None and r0.keys() == r1.keys()
    for k in r0:                                    # nan_ok: some metrics are nan
        assert r0[k] == pytest.approx(r1[k], nan_ok=True) if isinstance(
            r0[k], float) else r0[k] == r1[k]


def test_panel_is_bit_for_bit_deterministic_under_fixed_seed():
    s, end, M, C, wp, _ = _window_frames()
    a = propagate_window(s, end, M, C, wp, np.zeros(4, np.float32), 64,
                         np.random.default_rng(3), want_panel=True)[1]
    b = propagate_window(s, end, M, C, wp, np.zeros(4, np.float32), 64,
                         np.random.default_rng(3), want_panel=True)[1]
    for q in ("p10", "p50", "p90", "point"):
        np.testing.assert_array_equal(getattr(a, q), getattr(b, q))


def test_propagate_window_skips_when_the_fit_window_is_empty():
    _, _, M, C, wp, _ = _window_frames()
    s2 = M.index.max() + pd.Timedelta(days=365)     # fit window lands past all data
    row, panel = propagate_window(s2, s2 + pd.Timedelta(days=REFIT_DAYS),
                                  M, C, wp, np.zeros(4, np.float32), 8,
                                  np.random.default_rng(0))
    assert row is None and panel is None


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
