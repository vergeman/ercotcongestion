"""Per-constraint weather-response vectors.

Every system covariate - system-wide or zonal: load, wind, solar, net load,
outages. But they're identical for every constraint in a given hour. So the
model can only rank constraints by their own history, never by how the
constraint responds to today's weather.

e.g.: hour 3 has system wide inputs, so every constraint (A,B,C) sees the same
thing at that time. But historically each input-area (load_north, wind_east,
solar_west, etc) will have a different correlation with mu and weather over
time, yielding this "historical correlation vector".

Outline roughly:
at week start s:

  1. Use 240 day history of hourly mu (M_win), and weather (X_win) and
     calculate per constraint and R correlation

  2. place it on every hourly row for every day for that week. That's 7 days,
     every hour, same correlation vector

  3. Next week (next s), slide new window 240 days, recalculate R, and assign
     new values again.

Keeps consistent cadence, refit days, and window days with rest of model. Note
these correlations are placed in panel next to changing hourly inputs,
side-by-side. So a constraint gets 1. current: "high north load", and 2.
historic: "also tends to be sensitive to north load"

We correlate a constraint's own realized μ against each published
zonal/regional forecast over the trailing window, and the constraint tells us
what weather makes it bind.

"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from compute.mu_forecast.panel.build import BIND_DEADBAND
from compute.sf_map.geography.derive import refit_grid
from compute.time import normalize_ct_day

log = logging.getLogger("compute.mu_forecast.covariates.weather")

# Same trailing span and cadence as the SF map's fit window
from compute.sf_map.config import REFIT_DAYS, WINDOW_DAYS

# A window this short likely cannot support a wortwhile correlation;
# constraints before the earliest training margin get NaN instead
MIN_WINDOW_HOURS = 24 * 28

# The published ERCOT geography. Load is zonal (NP3-561), wind and solar are
# regional (NP4-742 / NP4-745). System-wide totals are deliberately excluded;
# (they are the same number for every constraint, so a correlation against them
# carries no cross-constraint information which is what this module exists to
# add.) `net_load` is kept because it is the physical driver, and a
# constraint's sensitivity to it is still constraint-specific.
WX_LOAD = ("coast", "east", "far_west", "north", "north_central",
           "south_central", "southern", "west")
WX_WIND = ("panhandle", "coastal", "south", "west", "north")
WX_SOLAR = ("centerwest", "northwest", "farwest", "fareast", "southeast", "centereast")


def wx_sources() -> dict[str, str]:
    """`system_panel` column → the `wx_corr_*` feature it produces."""
    src = {f"load_{z}": f"wx_corr_load_{z}" for z in WX_LOAD}
    src |= {f"stwpf_{r}": f"wx_corr_wind_{r}" for r in WX_WIND}
    src |= {f"stppf_{r}": f"wx_corr_solar_{r}" for r in WX_SOLAR}
    src["net_load"] = "wx_corr_net_load"
    return src


def _zscore(A: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """converts matrix of values to z-score; so disparate values are comparable

    A constraint that never bound is a constant-zero column: its correlation
    with anything is undefined (not zero).

    Returning 0.0 there would tell the model "this constraint is insensitive to
    load"; NaN says "we do not know"

    """
    mu = np.nanmean(A, axis=0)
    sd = np.nanstd(A, axis=0)
    ok = sd > 0
    Z = (A - mu) / np.where(ok, sd, 1.0)
    return Z, ok


def response_vectors(M_win: pd.DataFrame, X_win: pd.DataFrame) -> pd.DataFrame:
    """Correlate every constraint's μ against every weather column. One window.

    `M_win` is (hours × constraints) shadow prices
    `X_win` is (hours × weather) from `system_panel`.

    Both must already be restricted to the trailing window.

    μ is the magnitude series, zeros included (|μ| > BIND_DEADBAND, else 0),
    the same series persistence is made of.

    """
    # weather sources
    src = {c: name for c, name in wx_sources().items() if c in X_win.columns}
    if not src:
        return pd.DataFrame(index=M_win.columns)

    hours = M_win.index.intersection(X_win.index)
    if len(hours) < 2:
        return pd.DataFrame(index=M_win.columns)

    mu = M_win.loc[hours].fillna(0.0).abs()
    mu = mu.where(mu > BIND_DEADBAND, 0.0)  # PANDAS where: np.where( if
                                            # condition KEEP, else 0)

    X = X_win.loc[hours, list(src)]         # filter hours with matching weather inputs

    # Drop hours where any weather column is missing.
    # every constraint must be correlated on the SAME hours, or the response vectors
    # are not comparable across constraints
    # axis=1 horizontal, so testing whether for the hour, do all columns have a value (T)
    keep = X.notna().all(axis=1).to_numpy()
    if keep.sum() < MIN_WINDOW_HOURS:
        return pd.DataFrame(index=M_win.columns)

    # for the retained hours, standardize each value so quantities are
    # comparable
    # Zm: mu magnitude, Zx: weather inputs
    # ok: mask if sd > 0
    # n: num hours
    Zm, ok_m = _zscore(mu.to_numpy(float)[keep])
    Zx, ok_x = _zscore(X.to_numpy(float)[keep])
    n = int(keep.sum())

    # R: calculate correlations
    # Zm.T @ Zx: (constraints x hours) @ (hours x weather) -> (constraints x weather)
    # sum(z_mu * z_weather) / number_of_hours
    R = (Zm.T @ Zx) / n

    # negative filter, set the "Not oks" to undefined
    R[~ok_m, :] = np.nan          # never-binding constraint (row): undefined, not zero
    R[:, ~ok_x] = np.nan          # a flat forecast column: same

    out = pd.DataFrame(np.clip(R, -1.0, 1.0),
                       index=M_win.columns,
                       columns=[src[c] for c in X.columns])
    return out



def wx_panel(M: pd.DataFrame, sys_panel: pd.DataFrame, days: pd.DatetimeIndex,
             window_days: int = WINDOW_DAYS, refit_days: int = REFIT_DAYS,
             anchor: pd.Timestamp | None = None,
             on_refit=None) -> pd.DataFrame:
    """Per (delivery_day, constraint) weather-response vectors.

    For each refit boundary `s`, the correlations are computed on `[s -
    window_days, s)` and used for the delivery days in `[s, s + refit_days)`.

    A delivery day `D` therefore always reads a window whose last hour is
    strictly before `history_cutoff(D)`.

    Refit weekly, on the same grid and cadence as the SF map (and, when
    `anchor` is the first scored week, in the same phase).

    """
    grid = refit_grid(days, refit_days, anchor)  # step date range
    cols = [c for c in wx_sources() if c in sys_panel.columns]
    log.info("wx: %d weather columns × %d refit boundaries", len(cols), len(grid))

    # for each delivery *day* start
    frames, skipped = [], 0
    for s in grid:
        lo = s - pd.Timedelta(days=window_days)
        s_utc = normalize_ct_day(s)
        lo_utc = normalize_ct_day(lo)

        # M_win: constraint shadow prices, (hour x constraint)
        # X_win: system/weather input features (hour x feature)
        M_win = M.loc[(M.index >= lo_utc) & (M.index < s_utc)]
        X_win = sys_panel.loc[(sys_panel.index >= lo_utc) & (sys_panel.index < s_utc)]
        if len(M_win) < MIN_WINDOW_HOURS or X_win.empty:
            skipped += 1
            continue

        # R: constraint vs weather features; shadow vs input
        R = response_vectors(M_win, X_win)
        if R.empty or not R.notna().any().any():
            skipped += 1
            continue

        # week_days = s + days -> e.g [7 refit days: day 1, day 2, day 3 ...]
        week_days = days[(days >= s) & (days < s + pd.Timedelta(days=refit_days))]
        if on_refit is not None:
            on_refit(week_days, R)
        else:
            for d in week_days:
                f = R.copy()
                f["delivery_day"] = d
                f.index.name = "key"
                frames.append(f.reset_index())

    if skipped:
        log.info("wx: %d/%d boundaries had too little history (the earliest "
                 "training margin — honest NaN, not a fill)", skipped, len(grid))
    if on_refit is not None or not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).set_index(["delivery_day", "key"])
