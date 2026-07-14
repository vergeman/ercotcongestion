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

from compute.mu.features import (BIND_DEADBAND, audit_leakage, binding_history,
                                 calendar_features, dam_close, delivery_day_of,
                                 history_cutoff, net_load_regime)

D = pd.Timestamp("2025-08-02")  # a delivery day; DAM closed 2025-08-01 10:00 CT


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
    from compute.mu.features import candidate_keys
    hist = pd.DataFrame(
        {"binds_28d": [10, 0, 3, 0, 0]},
        index=pd.MultiIndex.from_product([[D], list("abcde")],
                                         names=["delivery_day", "key"]))
    assert len(candidate_keys(hist, "all")) == 5
    assert len(candidate_keys(hist, "active_28d")) == 2


def test_unknown_candidate_policy_is_refused():
    from compute.mu.features import candidate_keys
    with pytest.raises(ValueError, match="unknown candidate policy"):
        candidate_keys(pd.DataFrame(), "whatever_looks_best")


def test_delivery_day_is_local_not_utc():
    """19:00 CT on Aug 1 is 00:00 UTC on Aug 2. The delivery day is Aug 1.

    Getting this wrong would misassign every evening hour to the next day — and
    with it, every hour's DAM close.
    """
    ts = pd.Timestamp("2025-08-02 00:00", tz="UTC")
    assert delivery_day_of([ts])[0] == pd.Timestamp("2025-08-01")
