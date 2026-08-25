"""The covariate panel (plan/0085 commit 2).

Acceptance: *"No feature reads data unavailable at DAM close — asserted by a test
that fails on a deliberately leaked actual."* That is `test_audit_leakage_*` and
`test_binding_history_cannot_see_the_delivery_day`, which plant the leak rather
than merely assert its absence: a leak test that never sees a leak is a test of
nothing.

The other half of the risk is the *opposite* error — being so cautious that a full
day of legitimate, freshly-published history is thrown away. `history_cutoff` is
therefore pinned from both sides.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.mu_forecast.features import (BIND_DEADBAND, ERCOT_TZ, audit_leakage,
                                 binding_history, calendar_features, ct_day_bounds,
                                 dam_close, delivery_day_of, history_cutoff,
                                 net_load_regime, _attach_refit_features,
                                 _dam_close_expr, _vintage_cutoff_expr)

D = pd.Timestamp("2025-08-02")  # a delivery day; DAM closed 2025-08-01 10:00 CT


def test_refit_features_attach_like_a_left_merge_without_copying_the_panel():
    days = pd.DatetimeIndex([pd.Timestamp("2025-08-01"), pd.Timestamp("2025-08-02")])
    panel = pd.DataFrame({
        "delivery_day": [days[0], days[0], days[1], days[1]],
        "key": ["A|c", "MISSING|c", "B|c", "A|c"],
        "base": np.array([1, 2, 3, 4], dtype="float32"),
    })
    values = pd.DataFrame(
        {"geo_x": [1.25, 2.5], "geo_y": [3.75, 5.0]},
        index=pd.Index(["A|c", "B|c"], name="key"),
    )

    expected = panel.merge(values.reset_index(), on="key", how="left")
    expected[["geo_x", "geo_y"]] = expected[["geo_x", "geo_y"]].astype("float32")
    _attach_refit_features(panel, days, values)

    pd.testing.assert_frame_equal(panel, expected)


# ------------------------------------------------------------- the clock

def test_dam_close_is_ten_am_central_the_day_before():
    close = dam_close(D)
    assert close == pd.Timestamp("2025-08-01 15:00", tz="UTC")  # 10:00 CDT
    assert close.tz_convert("America/Chicago").hour == 10


def test_history_cutoff_admits_all_of_the_previous_day():
    """The point of the module docstring, as an assertion.

    Day D-1's DAM cleared and posted on D-2, so at DAM close on D-1 its whole
    24-hour outcome is public. Cutting history at the prediction instant (10:00)
    would silently discard the freshest 14 hours of the most predictive signal
    available.
    """
    cut = history_cutoff(D)
    last_hour_of_prev_day = pd.Timestamp("2025-08-01 23:00",
                                         tz="America/Chicago").tz_convert("UTC")
    assert last_hour_of_prev_day < cut          # D-1 23:00 is IN
    assert dam_close(D) < cut                   # and it is after the prediction instant

    first_hour_of_D = pd.Timestamp("2025-08-02 00:00",
                                   tz="America/Chicago").tz_convert("UTC")
    assert first_hour_of_D >= cut               # day D itself is OUT — that is the target


def test_ct_day_bounds_matches_hero_window_across_dst():
    """Same DST-aware [start, end) hero_window.delivery_bounds computes, from the
    pandas side: 23h/24h/25h across spring-forward/fall-back, and ordinary days
    keep the plain 24h span."""
    from compute.analysis.hero_window import delivery_bounds

    for day, hours in [("2025-08-02", 24), ("2026-03-08", 23), ("2026-11-01", 25)]:
        start, end = ct_day_bounds(pd.Timestamp(day).date())
        assert (end - start) == pd.Timedelta(hours=hours)
        want_start, want_end = delivery_bounds(pd.Timestamp(day).date())
        assert start == pd.Timestamp(want_start)
        assert end == pd.Timestamp(want_end)


def test_ct_day_bounds_naive_date_names_the_ct_day_directly():
    start, _ = ct_day_bounds(pd.Timestamp("2025-08-02"))
    assert start == pd.Timestamp("2025-08-02 05:00", tz="UTC")   # CDT


def test_ct_day_bounds_is_idempotent_on_an_already_anchored_instant():
    """Re-deriving bounds from the CT-midnight instant they produced is a no-op —
    the property every block-boundary caller in the pipeline relies on."""
    start, _ = ct_day_bounds(pd.Timestamp("2025-08-02"))
    start2, end2 = ct_day_bounds(start)
    assert start2 == start
    assert end2 - start2 == pd.Timedelta(hours=24)


def test_vintage_cutoff_expr_is_a_no_op_without_one():
    """No `vintage_cutoff` → the bare DAM-close expression, no bound param — an
    uncapped caller's query text and plan are unchanged (0133)."""
    expr, params = _vintage_cutoff_expr("interval_ts", None)
    assert expr == _dam_close_expr("interval_ts")
    assert params == ()


def test_vintage_cutoff_expr_wraps_dam_close_in_least_with_one():
    cutoff = pd.Timestamp("2025-05-31 12:00", tz="UTC")
    expr, params = _vintage_cutoff_expr("interval_ts", cutoff)
    assert expr == f"LEAST({_dam_close_expr('interval_ts')}, %s)"
    assert params == (cutoff,)


# ------------------------------------------------------------- the leak audit

def _panel(vintages, days=(D,)) -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC")
    for d in days:
        idx = idx.append(pd.date_range(
            pd.Timestamp(d).tz_localize("America/Chicago"),
            periods=24, freq="h", tz="America/Chicago").tz_convert("UTC"))
    return pd.DataFrame({"vintage_load": pd.to_datetime(vintages)}, index=idx)


def test_audit_leakage_passes_a_vintage_published_before_dam_close():
    clean = _panel([dam_close(D) - pd.Timedelta(minutes=30)] * 24)
    rep = audit_leakage(clean)
    assert rep.loc[0, "n_leaks"] == 0
    assert rep.loc[0, "min_slack_h"] == pytest.approx(0.5)


def test_audit_leakage_catches_a_vintage_published_after_dam_close():
    """The deliberately leaked read. One hour late is still a leak.

    This is the test that would have caught the old wind/solar tables, whose rows
    were published a median of +48.9h AFTER the hour they describe — 0.0% of them
    admissible, and nothing in the schema or the code said so.
    """
    leaked = _panel([dam_close(D) + pd.Timedelta(hours=1)] * 24)
    rep = audit_leakage(leaked)
    assert rep.loc[0, "n_leaks"] == 24
    assert rep.loc[0, "min_slack_h"] == pytest.approx(-1.0)


def test_audit_leakage_catches_a_single_bad_row_among_good_ones():
    """A leak does not have to be systematic to invalidate the gate."""
    vintages = [dam_close(D) - pd.Timedelta(hours=1)] * 24
    vintages[7] = dam_close(D) + pd.Timedelta(minutes=15)
    rep = audit_leakage(_panel(vintages))
    assert rep.loc[0, "n_leaks"] == 1
    assert rep.loc[0, "min_slack_h"] < 0


# ------------------------------------------------------------- binding history

@pytest.fixture
def M() -> pd.DataFrame:
    """40 days of hourly shadow prices, two constraints."""
    idx = pd.date_range("2025-07-01", periods=40 * 24, freq="h", tz="UTC")
    return pd.DataFrame(0.0, index=idx, columns=["A|c", "B|c"])


def test_binding_history_cannot_see_the_delivery_day(M):
    """THE leak test for the history features.

    Plant an enormous bind on day D itself — the very thing being predicted. Every
    feature must be byte-identical to the panel where day D is quiet. If this test
    ever fails, the model is reading its own target.
    """
    M.loc[:, "A|c"] = 0.0
    M.loc["2025-07-20":"2025-07-25", "A|c"] = 50.0     # real, admissible past

    quiet = binding_history(M, pd.DatetimeIndex([D]))

    leaked = M.copy()
    day_d = (pd.date_range(D.tz_localize("America/Chicago"), periods=24, freq="h")
             .tz_convert("UTC"))
    leaked.loc[leaked.index.isin(day_d), "A|c"] = 9999.0
    after = binding_history(leaked, pd.DatetimeIndex([D]))

    pd.testing.assert_frame_equal(quiet, after)


def test_binding_history_does_use_the_previous_day(M):
    """The other side of the same knife: D-1 is admissible and must be USED.

    A cutoff that cautiously stopped at the 10:00 prediction instant would make
    this test fail — and would quietly cost the model its freshest day of signal.
    """
    day_before = (pd.date_range(pd.Timestamp("2025-08-01").tz_localize("America/Chicago"),
                                periods=24, freq="h").tz_convert("UTC"))
    quiet = binding_history(M, pd.DatetimeIndex([D]))

    M.loc[M.index.isin(day_before), "A|c"] = 50.0
    after = binding_history(M, pd.DatetimeIndex([D]))

    assert quiet.loc[(D, "A|c"), "binds_1d"] == 0
    assert after.loc[(D, "A|c"), "binds_1d"] == 24
    assert after.loc[(D, "A|c"), "days_since_bind"] == 0


def test_binding_history_respects_the_deadband(M):
    """Numerical dust is not a bind."""
    day_before = (pd.date_range(pd.Timestamp("2025-08-01").tz_localize("America/Chicago"),
                                periods=24, freq="h").tz_convert("UTC"))
    M.loc[M.index.isin(day_before), "A|c"] = BIND_DEADBAND * 0.5
    h = binding_history(M, pd.DatetimeIndex([D]))
    assert h.loc[(D, "A|c"), "binds_1d"] == 0


def test_never_binding_constraint_gets_an_honest_days_since(M):
    h = binding_history(M, pd.DatetimeIndex([D]))
    assert h.loc[(D, "B|c"), "binds_28d"] == 0
    assert h.loc[(D, "B|c"), "bind_rate_life"] == 0.0
    assert h.loc[(D, "B|c"), "days_since_bind"] > 0   # not 0, which would read as "bound yesterday"


# ------------------------------------------------- lagged mu (plan/0088 commit 2)

def _local_day(day: str) -> pd.DatetimeIndex:
    """The 24 UTC hours belonging to an ERCOT-local delivery day."""
    return (pd.date_range(pd.Timestamp(day).tz_localize(ERCOT_TZ),
                          periods=24, freq="h").tz_convert("UTC"))


def test_lag_mu_1d_is_exactly_yesterdays_realized_mu(M):
    """**The acceptance criterion for commit 2, stated as arithmetic.**

    Plant a known shape on D-1 — 6 hours at $120, 18 hours slack — and demand the
    exact number back. `lag_mu_1d` is the mean over ALL 24 hours (6*120/24 = 30.0),
    not the mean over binding hours (120.0): a slack hour's mu is an observed zero,
    and that is the same convention `score.mu_persistence` uses. Asserting the
    exact value is what makes the two definitions impossible to confuse later.
    """
    d_minus_1 = _local_day("2025-08-01")
    M.loc[M.index.isin(d_minus_1[:6]), "A|c"] = 120.0

    h = binding_history(M, pd.DatetimeIndex([D]))

    assert h.loc[(D, "A|c"), "lag_mu_1d"] == pytest.approx(6 * 120.0 / 24)
    assert h.loc[(D, "A|c"), "lag_max_mu_1d"] == pytest.approx(120.0)
    # and the 7d window sees the same six hours spread over seven days
    assert h.loc[(D, "A|c"), "lag_mu_7d"] == pytest.approx(6 * 120.0 / (7 * 24))
    assert h.loc[(D, "A|c"), "lag_max_mu_7d"] == pytest.approx(120.0)


def test_lag_mu_cannot_see_the_delivery_day(M):
    """The leak test, planted rather than asserted — as for the rest of `binding_history`.

    Day D is the target. Load it with the largest mu in the fixture and demand that
    every lag column is byte-identical to the run where day D is quiet. A `lag_*`
    column that moved here would be reading its own answer, and it would look like
    a spectacular result.
    """
    M.loc[M.index.isin(_local_day("2025-08-01")), "A|c"] = 40.0   # admissible D-1

    quiet = binding_history(M, pd.DatetimeIndex([D]))

    leaked = M.copy()
    leaked.loc[leaked.index.isin(_local_day("2025-08-02")), "A|c"] = 9999.0
    after = binding_history(leaked, pd.DatetimeIndex([D]))

    lag = [c for c in quiet.columns if c.startswith("lag_")]
    assert lag, "the lag columns vanished — this test would pass vacuously"
    pd.testing.assert_frame_equal(quiet[lag], after[lag])


def test_lag_mu_is_zero_not_nan_for_a_quiet_constraint(M):
    """A constraint that did not bind yesterday has a mu of 0.0, and that is an
    OBSERVATION, not a hole.

    This is the one place in the panel where a zero is right and a NaN is wrong,
    so it is pinned. `mean_mu_28d` is the bind-conditional quantity and is
    genuinely undefined for a never-binder; `lag_mu_*` is not, and confusing the
    two would hand the model a NaN for precisely the quiet constraints whose
    quietness is the most predictive thing about them.
    """
    h = binding_history(M, pd.DatetimeIndex([D]))
    for c in ("lag_mu_1d", "lag_mu_7d", "lag_max_mu_1d", "lag_max_mu_7d"):
        assert h.loc[(D, "B|c"), c] == 0.0


def test_lag_mu_respects_the_deadband(M):
    """Sub-deadband dust is not a bind, and it contributes no magnitude either —
    `mu` is masked by `binds`, so the two definitions cannot drift apart."""
    M.loc[M.index.isin(_local_day("2025-08-01")), "A|c"] = BIND_DEADBAND * 0.5
    h = binding_history(M, pd.DatetimeIndex([D]))
    assert h.loc[(D, "A|c"), "lag_mu_1d"] == 0.0
    assert h.loc[(D, "A|c"), "lag_max_mu_1d"] == 0.0


def test_lag_mu_1d_uses_the_days_real_hour_count_not_a_hardcoded_24():
    """A spring-forward day has 23 hours. Dividing its mu-sum by 24 would understate
    it by ~4% — small, silent, and exactly the kind of thing that survives for a year.

    2026-03-08 is the DST transition; 2026-03-09 is the delivery day whose D-1 it is.
    """
    idx = pd.date_range("2026-03-01", "2026-03-10", freq="h", tz="UTC")
    M = pd.DataFrame(0.0, index=idx, columns=["A|c"])

    d_minus_1 = delivery_day_of(M.index) == pd.Timestamp("2026-03-08")
    assert d_minus_1.sum() == 23, "fixture is not actually a spring-forward day"
    M.loc[d_minus_1, "A|c"] = 46.0

    h = binding_history(M, pd.DatetimeIndex([pd.Timestamp("2026-03-09")]))
    # every hour of a 23-hour day at $46 -> the mean is $46, not 23*46/24 = $44.08
    assert h.loc[(pd.Timestamp("2026-03-09"), "A|c"), "lag_mu_1d"] == pytest.approx(46.0)


# ------------------------------------------------------------- regime edges

def test_net_load_regime_edges_come_only_from_the_fit_window():
    """Quantile edges fitted on train+test would encode the test distribution.

    Here the scored tail is far outside anything in the fit window. The edges must
    not move to accommodate it — the tail should simply pile into the top bucket.
    """
    idx = pd.date_range("2025-07-01", periods=200, freq="h", tz="UTC")
    panel = pd.DataFrame({"net_load": np.arange(200.0)}, index=idx)
    fit = idx[:100]

    labels = net_load_regime(panel, fit, n_buckets=4)
    edges_seen = labels.loc[fit].max()

    panel_shifted = panel.copy()
    panel_shifted.loc[idx[100:], "net_load"] = 1e6      # an absurd scored tail
    labels2 = net_load_regime(panel_shifted, fit, n_buckets=4)

    # Fit-window labels are untouched by anything outside the fit window.
    pd.testing.assert_series_equal(labels.loc[fit], labels2.loc[fit])
    assert edges_seen == labels2.loc[fit].max()
    assert (labels2.loc[idx[100:]] == 3).all()          # all in the top bucket


def test_calendar_is_derivable_from_the_clock_alone():
    idx = pd.date_range("2025-08-02", periods=48, freq="h", tz="UTC")
    cal = calendar_features(idx)
    assert set(cal.columns) == {"hour", "dow", "month", "is_weekend",
                                "hour_sin", "hour_cos"}
    assert cal["hour"].between(0, 23).all()
    # Hour 23 and hour 0 are adjacent on the circle, which the raw integer hides.
    assert cal["hour_cos"].max() == pytest.approx(1.0)


# ------------------------------------------------------------- DST

def test_spring_forward_hour_does_not_duplicate_the_index():
    """`outages_zonal` has no dst_flag and reports 24 hour-endings every day —
    including the 23-hour spring-forward day, whose 02:00 does not exist locally.
    Shifting it forward lands it on 03:00, colliding with the real row, and the
    concat in `system_panel` then dies with "Reindexing only valid with uniquely
    valued Index". Found on the full-range run; pinned here.
    """
    day = pd.Timestamp("2025-03-09")          # ERCOT spring-forward
    local = (pd.to_datetime([day] * 24)
             + pd.to_timedelta(range(24), unit="h"))
    ts = (local.tz_localize("America/Chicago", ambiguous=True,
                            nonexistent="shift_forward").tz_convert("UTC"))
    assert ts.duplicated().any(), "fixture must reproduce the collision"

    df = pd.DataFrame({"x": range(24)}, index=ts)
    deduped = df[~df.index.duplicated(keep="last")]
    assert not deduped.index.duplicated().any()
    assert len(deduped) == 23                 # a spring-forward day IS 23 hours


# ------------------------------------------------------------- candidate policy

def test_candidate_policy_changes_the_base_rate_not_just_the_row_count():
    """The policy is a modelling choice, so it gets a test that says why.

    `active_28d` drops constraints with no recent binds. Those are almost all
    negatives, so dropping them RAISES the positive rate — which moves every
    headline number in commit 4. A reader must not mistake this for a free
    row-count optimisation.
    """
    from compute.mu_forecast.features import candidate_keys
    hist = pd.DataFrame(
        {"binds_28d": [10, 0, 3, 0, 0]},
        index=pd.MultiIndex.from_product([[D], list("abcde")],
                                         names=["delivery_day", "key"]))
    assert len(candidate_keys(hist, "all")) == 5
    assert len(candidate_keys(hist, "active_28d")) == 2


def test_unknown_candidate_policy_is_refused():
    from compute.mu_forecast.features import candidate_keys
    with pytest.raises(ValueError, match="unknown candidate policy"):
        candidate_keys(pd.DataFrame(), "whatever_looks_best")


def test_delivery_day_is_local_not_utc():
    """19:00 CT on Aug 1 is 00:00 UTC on Aug 2. The delivery day is Aug 1.

    Getting this wrong would misassign every evening hour to the next day — and
    with it, every hour's DAM close.
    """
    ts = pd.Timestamp("2025-08-02 00:00", tz="UTC")
    assert delivery_day_of([ts])[0] == pd.Timestamp("2025-08-01")
