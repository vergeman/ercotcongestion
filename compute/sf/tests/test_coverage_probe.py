"""Tier decomposition (plan/0084 commit 2).

The probe's whole job is to split novel mu-mass into the three tiers with three
different fixes, so the tests plant one constraint of each kind and check it
lands where it belongs — and that the tiers partition the novel mass exactly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.experiments.sf.coverage import admission_stats, probe

D0 = pd.Timestamp("2025-01-01")
WINDOW, REFIT, MIN_HOURS, MIN_HIST = 60, 7, 25, 100
# On the refit grid (anchored at D0 + WINDOW, step 7d) and past the history bar.
SCORE_WEEK = D0 + pd.Timedelta(days=200)


def _panel(n_days: int = 400) -> pd.DataFrame:
    idx = pd.date_range(D0, periods=n_days * 24, freq="h")
    return pd.DataFrame(0.0, index=idx, columns=["A", "B", "C", "BG"])


def _bind(M: pd.DataFrame, key: str, day_from: float, hours: int, mu: float = 50.0):
    """Set `hours` consecutive binding hours starting `day_from` days in."""
    lo = D0 + pd.Timedelta(days=day_from)
    M.loc[lo:lo + pd.Timedelta(hours=hours - 1), key] = mu


@pytest.fixture
def planted() -> pd.DataFrame:
    M = _panel()
    # BG: always binding — the fit always keeps it, so it is covered, not novel.
    M["BG"] = 10.0
    # A — warm-startable: 30h early (an earlier 60d window keeps it), silent
    # through the scored week's fit window, then binds in the scored week.
    _bind(M, "A", 60, 30)
    # B — seen, never fitted: two 5h episodes, never 25h inside any one window.
    _bind(M, "B", 70, 5)
    _bind(M, "B", 100, 5)
    # C — genuinely new: its first bind ever is in the scored week itself.
    for key in ("A", "B", "C"):
        _bind(M, key, 200, 10, mu=100.0)
    # C binds again later. Without a RECURRENCE, admitting a constraint buys no
    # coverage — it got its column after the only mass it ever carried. The
    # coverage payoff of a lower bar lives entirely in the repeat offenders.
    _bind(M, "C", 250, 10, mu=100.0)
    return M


@pytest.fixture
def row(planted) -> pd.Series:
    df = probe(planted, WINDOW, REFIT, MIN_HOURS, MIN_HIST)
    hit = df[df["week"] == SCORE_WEEK.date()]
    assert len(hit) == 1, f"scored weeks: {list(df.week)}"
    return hit.iloc[0]


def test_tiers_land_where_planted(row):
    assert row.n_warmstartable == 1   # A
    assert row.n_seen_unfitted == 1   # B
    assert row.n_new == 1             # C


def test_first_ever_bind_in_the_scored_week_is_new_not_seen(row):
    """The lookahead that would actually bite: if `ever_seen` were built from the
    whole panel instead of [data_min, s), C's scored-week bind would make it look
    like history and it would land in tier B — inflating what a warm-start can
    reach. It must be C."""
    assert row.n_new == 1
    assert row.mass_new > 0


def test_tiers_partition_the_novel_mass(row):
    total = row.mass_warmstartable + row.mass_seen_unfitted + row.mass_new
    assert total == pytest.approx(row.novel_mass)
    assert row.share_warmstartable + row.share_seen_unfitted + row.share_new \
        == pytest.approx(1.0)


def test_always_binding_constraint_is_covered_not_novel(row):
    """BG binds every hour, so the fit keeps it and its mass is not in the gap."""
    assert 0.0 < row.coverage < 1.0
    assert row.novel_mass < row.total_mass


def test_ceiling_counts_only_the_warm_startable_tier(row):
    """coverage_ceiling = 1 - (B + C)/total: a perfect warm-start recovers A and
    nothing else. The lift it reports must equal A's share of total mass."""
    assert row.ceiling_lift == pytest.approx(
        row.mass_warmstartable / row.total_mass
    )
    assert row.coverage_ceiling > row.coverage


def test_warm_start_age_is_positive_and_backward_looking(row):
    """A was last fitted at an EARLIER boundary, so the row a library would
    inherit is stale by a real number of days — never 0 (that would mean the
    current fit had it, i.e. it was never novel)."""
    assert row.mean_age_days > 0
    assert np.isfinite(row.mean_age_days)


def test_history_bar_admits_only_weeks_with_a_real_band(planted):
    df = probe(planted, WINDOW, REFIT, MIN_HOURS, min_history_days=MIN_HIST)
    assert (df.hist_days >= MIN_HIST).all()
    # hist_days is the band BEHIND the fit window, and it grows with time.
    assert df.hist_days.is_monotonic_increasing


def test_latency_excludes_constraints_born_before_the_panel(planted):
    """BG binds from hour zero, so its 'first bind' is an artifact of where the
    data starts, not a birth. Counting it would report a latency for a lifetime
    we never observed. Only A, B and C are born inside the window."""
    st = admission_stats(planted, WINDOW, REFIT, MIN_HOURS, MIN_HIST)
    assert st["n_new_keys"] == 3


def test_min_hours_is_what_rejects_the_thin_constraints(planted):
    """B (10h total) and C (10h) never reach 25h in a window, so they are never
    admitted at all. Drop the bar to 5h and both get columns — this is the tier-B
    mechanism the real panel says carries 58% of the gap."""
    strict = admission_stats(planted, WINDOW, REFIT, min_hours=25,
                             min_history_days=MIN_HIST)
    loose = admission_stats(planted, WINDOW, REFIT, min_hours=5,
                            min_history_days=MIN_HIST)
    assert strict["n_admitted"] == 1          # A only
    assert strict["admit_rate"] == pytest.approx(1 / 3)
    assert strict["never_admitted_mass_share"] > 0

    assert loose["admit_rate"] == pytest.approx(1.0)
    assert loose["never_admitted_mass_share"] == pytest.approx(0.0)
    assert loose["blind_mass_share"] < strict["blind_mass_share"]
    assert loose["coverage"] > strict["coverage"]


def test_refit_cadence_bounds_the_latency(planted):
    """A constraint can only be admitted at a refit boundary, so the cadence is a
    floor on how fast a new constraint can get a column."""
    weekly = admission_stats(planted, WINDOW, refit_days=7, min_hours=MIN_HOURS,
                             min_history_days=MIN_HIST)
    daily = admission_stats(planted, WINDOW, refit_days=1, min_hours=MIN_HOURS,
                            min_history_days=MIN_HIST)
    assert daily["median_latency_days"] < weekly["median_latency_days"]


def test_legacy_lookback_mode_emits_the_r2_columns(planted):
    """The fixed-band mode exists to keep 0082's 0.507/0.303 reproducible."""
    df = probe(planted, window_days=60, refit_days=REFIT, min_hours=MIN_HOURS,
               lookback_days=365)
    assert "seasonal_any_share" in df.columns
    assert "seasonal_material_share" in df.columns
    # Legacy anchors the grid at data_min + lookback, not data_min + window.
    assert df.week.min() >= (D0 + pd.Timedelta(days=365)).date()
