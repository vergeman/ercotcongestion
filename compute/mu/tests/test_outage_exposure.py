"""Per-constraint outage exposure (plan/0089 commit 3).

Four acceptance criteria live here, and they are the ones the whole arm turns on:

  * the covariate for delivery day D reads only the **D-4 vintage** (newest snapshot
    posted ≤ D-1) and **never a later one** — planting a future snapshot must change
    nothing;
  * the |SF| behind day D was fit on a window that **closed on or before D** — planting a
    congestion spike on day D itself must change nothing;
  * the exposure is **per-constraint** — two constraints on the same day get different
    values (the whole point; the zonal fallback cannot);
  * `out_exposure_planned` uses **Planned End Date** — MW expected still out *on D*, not
    merely MW out in the snapshot.

The leak tests plant the leak (a future vintage, a future price) and demand the covariate
stay blind to it — a leak test that never sees a leak tests nothing (0088's discipline).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from compute.mu.outage_exposure import (_exposure, _vintage,
                                        outage_exposure_panel)


# ------------------------------------------------------------- deterministic units

def test_vintage_is_newest_posted_on_or_before_D_minus_1():
    posted = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    # delivery day the 4th -> D-1 is the 3rd, which is admissible.
    assert _vintage(posted, pd.Timestamp("2026-01-04")) == date(2026, 1, 3)
    # delivery day the 3rd -> the 3rd's own snapshot (posted that morning, after close
    # for D=3? no — posted D=3 is NOT ≤ D-1) must be excluded; newest admissible is the 2nd.
    assert _vintage(posted, pd.Timestamp("2026-01-03")) == date(2026, 1, 2)
    # before any snapshot exists -> None (NaN downstream).
    assert _vintage(posted, pd.Timestamp("2026-01-01")) is None


def test_exposure_is_per_constraint():
    """Two constraints weighting different SPs get different exposure to the same MW."""
    W = pd.DataFrame([[0.9, 0.1], [0.1, 0.9]],
                     index=["K1", "K2"], columns=["SP_A", "SP_B"])
    e = _exposure(W, pd.Series({"SP_A": 100.0}))
    assert e[0] != e[1] and e[0] == pytest.approx(90.0) and e[1] == pytest.approx(10.0)


# ------------------------------------------------------------- end-to-end fixture

D0 = pd.Timestamp("2026-02-01")          # first delivery day / refit anchor
CT = "America/Chicago"


def _panels():
    """M (hours × K1,K2) and C (hours × SP_A,SP_B) over the fit window [D0-20d, D0).

    K1 binds correlated with SP_A, K2 with SP_B, on disjoint hours — so the honest SF
    places K1's |mass| on SP_A and K2's on SP_B, without either ever co-binding."""
    base = (D0 - pd.Timedelta(days=10)).tz_localize("UTC")
    hours = pd.DatetimeIndex([base + pd.Timedelta(hours=i) for i in range(24)])
    M = pd.DataFrame(0.0, index=hours, columns=["K1", "K2"])
    C = pd.DataFrame(0.0, index=hours, columns=["SP_A", "SP_B"])
    for i in range(24):
        val = 10.0 + i
        if i < 12:
            M.iloc[i, 0] = val; C.iloc[i, 0] = val      # K1 <-> SP_A
        else:
            M.iloc[i, 1] = val; C.iloc[i, 1] = val      # K2 <-> SP_B
    return M, C


def _outages(future: bool = False) -> pd.DataFrame:
    """The D-1 vintage for D0 carries two outages on SP_A: one still out on D0, one that
    ended before it. `future=True` adds a richer snapshot posted ON D0 — inadmissible for
    D0, and the leak test asserts it changes nothing."""
    d0 = D0.date()
    d_prev = (D0 - pd.Timedelta(days=1)).date()
    rows = [
        # posted D0-1 (admissible for D0): still-out + already-ended, same SP + MW.
        (d_prev, "SP_A", 100.0,
         pd.Timestamp(D0 + pd.Timedelta(days=5), tz="UTC"), "Natural Gas"),
        (d_prev, "SP_A", 100.0,
         pd.Timestamp(D0 - pd.Timedelta(days=1), tz="UTC"), "Natural Gas"),
    ]
    if future:
        rows.append((d0, "SP_A", 999.0,
                     pd.Timestamp(D0 + pd.Timedelta(days=30), tz="UTC"), "Natural Gas"))
    df = pd.DataFrame(rows, columns=["posted_date", "sp", "mw", "planned_end", "fuel"])
    df["planned_end"] = pd.to_datetime(df["planned_end"], utc=True)
    return df


def _panel(outages):
    return outage_exposure_panel(
        *_panels(), outages, days=pd.DatetimeIndex([D0]),
        window_days=20, refit_days=7, lam=1.0, min_hours=5, anchor=D0)


def test_planned_uses_planned_end_date_not_just_whats_out():
    """now = 200 MW out on SP_A; planned = only the 100 MW still out on D0. The |SF| that
    both dot is identical, so planned must be exactly half of now — independent of its
    value."""
    p = _panel(_outages())
    now = p.loc[(D0, "K1"), "out_exposure_now"]
    planned = p.loc[(D0, "K1"), "out_exposure_planned"]
    assert now > 0
    assert planned == pytest.approx(now / 2.0)


def test_no_leak_from_a_future_vintage():
    """A snapshot posted ON D0 is inadmissible for D0; D0's exposure is identical with and
    without it."""
    without = _panel(_outages(future=False)).loc[(D0, "K1"), "out_exposure_now"]
    with_future = _panel(_outages(future=True)).loc[(D0, "K1"), "out_exposure_now"]
    assert with_future == pytest.approx(without)


def test_sf_window_excludes_the_delivery_day():
    """A congestion spike on day D0 must not change D0's exposure — the SF behind D0 was
    fit strictly before it."""
    M, C = _panels()
    base = _panel(_outages()).loc[(D0, "K1"), "out_exposure_now"]
    spike_hours = pd.DatetimeIndex([D0.tz_localize("UTC") + pd.Timedelta(hours=h)
                                    for h in range(6)])
    M2 = pd.concat([M, pd.DataFrame(5000.0, index=spike_hours, columns=M.columns)])
    C2 = pd.concat([C, pd.DataFrame(5000.0, index=spike_hours, columns=C.columns)])
    spiked = outage_exposure_panel(M2, C2, _outages(), days=pd.DatetimeIndex([D0]),
                                   window_days=20, refit_days=7, lam=1.0, min_hours=5,
                                   anchor=D0).loc[(D0, "K1"), "out_exposure_now"]
    assert spiked == pytest.approx(base)


def test_two_constraints_get_different_exposure():
    """The whole point: with outage MW only on SP_A, K1 (which lives on SP_A) is exposed
    and K2 (on SP_B) is not — the zonal fallback would give them the same number."""
    p = _panel(_outages())
    k1 = p.loc[(D0, "K1"), "out_exposure_now"]
    k2 = p.loc[(D0, "K2"), "out_exposure_now"]
    assert k1 != k2 and k1 > k2
