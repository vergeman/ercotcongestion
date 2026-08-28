"""Per-constraint weather-response vectors (plan/0088 commit 4).

The acceptance criteria:

  * *"Weather trailing window is the same length as the map's fit window"*
  * *"a test asserts the correlation window ends before `history_cutoff(D)`"*

The second one carries the risk, and it carries it **alone**: `audit_leakage` is
built around vintage logic and inspects the forecasts' `posted_datetime` columns —
which are already clean here, because the forecasts are read at their DAM-close
vintage regardless. **A correlation window that ran six hours too late would leave
every vintage column innocent and the audit silent.** So the window is enforced in
`wx_panel` and pinned here, and nowhere else.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import compute.mu_forecast.covariates.weather as weather
from compute.mu_forecast.panel.availability import history_cutoff
from compute.mu_forecast.covariates.weather import (MIN_WINDOW_HOURS, response_vectors, wx_panel,
                                wx_sources)


def _hours(n_days: int, start: str = "2025-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n_days * 24, freq="h", tz="UTC")


def _sys(hours: pd.DatetimeIndex, seed: int = 0) -> pd.DataFrame:
    """A weather panel with the real column names and a real daily shape."""
    rng = np.random.default_rng(seed)
    h = hours.hour.to_numpy()
    base = 40000 + 12000 * np.sin((h - 6) / 24 * 2 * np.pi)
    X = pd.DataFrame(index=hours)
    for z in ("coast", "east", "far_west", "north", "north_central",
              "south_central", "southern", "west"):
        X[f"load_{z}"] = base / 8 + rng.normal(0, 300, len(hours))
    for r in ("panhandle", "coastal", "south", "west", "north"):
        X[f"stwpf_{r}"] = 3000 + rng.normal(0, 800, len(hours))
    for r in ("centerwest", "northwest", "farwest", "fareast", "southeast",
              "centereast"):
        X[f"stppf_{r}"] = np.clip(2000 * np.sin((h - 6) / 12 * np.pi), 0, None) \
            + rng.normal(0, 100, len(hours))
    X["net_load"] = base + rng.normal(0, 500, len(hours))
    return X


# ------------------------------------------------------------ the correlation

def test_a_constraint_that_binds_with_west_wind_is_told_so():
    """The whole point of the arm, as arithmetic.

    Constraint W binds exactly when west wind is high; constraint P binds exactly
    when panhandle wind is high. **The model has no way to tell these two apart
    today** — every covariate it holds is the same number for both in any given
    hour. The response vector must separate them, and must do so in the RIGHT
    column: W's strongest wind correlation is west, P's is panhandle.
    """
    hours = _hours(60)
    X = _sys(hours)
    M = pd.DataFrame(0.0, index=hours, columns=["W|c", "P|c"])
    M.loc[X["stwpf_west"] > X["stwpf_west"].quantile(0.7), "W|c"] = 50.0
    M.loc[X["stwpf_panhandle"] > X["stwpf_panhandle"].quantile(0.7), "P|c"] = 50.0

    R = response_vectors(M, X)

    wind = [c for c in R.columns if c.startswith("wx_corr_wind_")]
    assert R.loc["W|c", wind].idxmax() == "wx_corr_wind_west"
    assert R.loc["P|c", wind].idxmax() == "wx_corr_wind_panhandle"
    # and they are genuinely different vectors, which is the identity the model lacks
    assert R.loc["W|c", "wx_corr_wind_west"] > R.loc["P|c", "wx_corr_wind_west"]


def test_a_never_binding_constraint_gets_nan_not_zero():
    """**Zero is a claim; NaN is the truth.**

    A correlation of 0.0 tells the model "this constraint is insensitive to load".
    We do not know that — the constraint never bound, so its response is undefined.
    Handing the booster a confident zero for every quiet constraint would be
    inventing a covariate value, which is `build_panel`'s one prohibition.
    """
    hours = _hours(60)
    X = _sys(hours)
    M = pd.DataFrame(0.0, index=hours, columns=["QUIET|c"])
    R = response_vectors(M, X)
    assert R.loc["QUIET|c"].isna().all()


def test_correlations_are_bounded_and_signed():
    hours = _hours(60)
    X = _sys(hours)
    M = pd.DataFrame(0.0, index=hours, columns=["A|c"])
    # binds when net load is LOW — a real thing (wind-driven export congestion),
    # and the sign is the information
    M.loc[X["net_load"] < X["net_load"].quantile(0.3), "A|c"] = 40.0
    R = response_vectors(M, X)
    assert R["wx_corr_net_load"].between(-1, 1).all()
    assert R.loc["A|c", "wx_corr_net_load"] < 0


def test_the_deadband_is_the_same_one_binding_history_uses():
    """Sub-deadband dust is not a bind, here as everywhere. If these two
    definitions of "bound" ever drift apart, `lag_*` and `wx_*` would be describing
    different events under the same name."""
    hours = _hours(60)
    X = _sys(hours)
    M = pd.DataFrame(0.5, index=hours, columns=["DUST|c"])   # below BIND_DEADBAND
    R = response_vectors(M, X)
    assert R.loc["DUST|c"].isna().all()


def test_system_wide_columns_are_excluded():
    """A system-wide total is the same number for every constraint, so correlating
    against it adds no cross-constraint information — the only thing this arm is for."""
    src = wx_sources()
    assert not [c for c in src if "system_wide" in c]
    assert "net_load" in src          # kept: constraint-specific sensitivity to it


def test_every_source_column_maps_to_a_prefixed_feature():
    """The ablation selects this arm by the `wx_` prefix. A column that missed the
    prefix would silently land in `base` and contaminate the control."""
    assert all(f.startswith("wx_corr_") for f in wx_sources().values())


# ------------------------------------------------------- THE WINDOW (acceptance)

def test_wx_window_ends_before_the_history_cutoff():
    """**THE acceptance test.** The correlation window for delivery day D must not
    include a single hour at or after `history_cutoff(D)`.

    Planted, not asserted: day D's own weather is replaced with a signal so strong
    that any leak would dominate the correlation, and the vectors must not move. A
    window that ran even one day long would let a constraint's response vector be
    computed partly from the day it is being asked to predict — and unlike a
    lookahead *feature*, `audit_leakage` cannot see this one, because the forecast
    vintages stay perfectly clean either way.
    """
    hours = _hours(300)
    X = _sys(hours)
    M = pd.DataFrame(0.0, index=hours, columns=["A|c"])
    M.loc[X["net_load"] > X["net_load"].quantile(0.6), "A|c"] = 50.0

    days = pd.DatetimeIndex(sorted({d.normalize() for d in
                                    hours.tz_convert("America/Chicago")
                                    .tz_localize(None)}))
    anchor = days[250]
    before = wx_panel(M, X, days, window_days=200, refit_days=7, anchor=anchor)

    D = anchor
    cut = history_cutoff(D)

    # Rewrite EVERYTHING from the cutoff onward — the delivery day and beyond.
    M2, X2 = M.copy(), X.copy()
    fut = M2.index >= cut
    M2.loc[fut, "A|c"] = 900.0
    for c in X2.columns:
        X2.loc[fut, c] = -50000.0
    after = wx_panel(M2, X2, days, window_days=200, refit_days=7, anchor=anchor)

    pd.testing.assert_frame_equal(before.xs(D, level="delivery_day"),
                                  after.xs(D, level="delivery_day"))


def test_wx_window_is_the_same_length_as_the_maps_fit_window():
    """The acceptance criterion names the map's window, and the default is it."""
    from compute.sf_map.geography.derive import WINDOW_DAYS as SF_WINDOW
    from compute.evaluation.mu import WINDOW_DAYS as SCORE_WINDOW
    from compute.mu_forecast.covariates.weather import WINDOW_DAYS as WX_WINDOW
    assert WX_WINDOW == SF_WINDOW == SCORE_WINDOW == 240


def test_a_window_too_short_to_mean_anything_gives_nan_rather_than_a_number():
    """The earliest training margin has no history behind it. A correlation over 40
    hours is noise with a decimal point; it is left as a hole."""
    hours = _hours(10)
    X = _sys(hours)
    M = pd.DataFrame(50.0, index=hours, columns=["A|c"])
    assert len(hours) < MIN_WINDOW_HOURS
    assert response_vectors(M, X).empty


def test_wx_panel_is_constant_within_a_delivery_day():
    """Standing at DAM close, every hour of day D shares the same past — so a
    response vector that varied *within* day D could only do so by reading day D."""
    hours = _hours(120)
    X = _sys(hours)
    M = pd.DataFrame(0.0, index=hours, columns=["A|c"])
    M.loc[X["net_load"] > X["net_load"].median(), "A|c"] = 30.0
    days = pd.DatetimeIndex(sorted({d.normalize() for d in
                                    hours.tz_convert("America/Chicago")
                                    .tz_localize(None)}))
    wx = wx_panel(M, X, days, window_days=60, refit_days=7, anchor=days[70])
    # one row per (day, key) — the feature is a property of the day, not the hour
    assert not wx.index.duplicated().any()


@pytest.mark.parametrize(("day", "boundary"), [
    ("2026-07-07", "2026-07-07 05:00"),
    ("2026-12-07", "2026-12-07 06:00"),
])
def test_wx_fit_window_uses_ct_midnight_utc_bounds(monkeypatch, day, boundary):
    s = pd.Timestamp(day)
    lo = s - pd.Timedelta(days=28)
    start = pd.Timestamp(f"{lo.date()} {boundary[-5:]}", tz="UTC")
    end = pd.Timestamp(boundary, tz="UTC")
    hours = pd.date_range(start - pd.Timedelta(hours=1), end, freq="h")
    M = pd.DataFrame({"K": 1.0}, index=hours)
    seen = []

    def response(M_win, X_win):
        seen.append((M_win.index, X_win.index))
        return pd.DataFrame({"wx_corr_net_load": [1.0]}, index=["K"])

    monkeypatch.setattr(weather, "response_vectors", response)
    weather.wx_panel(M, _sys(hours), pd.DatetimeIndex([s]), window_days=28, anchor=s)

    expected = pd.date_range(start, end, freq="h", inclusive="left")
    assert len(seen) == 1
    pd.testing.assert_index_equal(seen[0][0], expected)
    pd.testing.assert_index_equal(seen[0][1], expected)
