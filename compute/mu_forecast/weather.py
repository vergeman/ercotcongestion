"""Per-constraint weather-response vectors.

plan/0088 commit 4.

**The gap this closes, stated exactly.** Every system covariate the model has — load,
wind, solar, net load, outages — is *system-wide or zonal*: **identical for every
constraint in a given hour.** So in any given hour the model can rank constraints only
by their own history, never by how *this* constraint responds to *today's* weather.
That is the whole of 0085 §5.6, and it is why persistence — which implicitly carries
topology state — beat the model on the tail.

**Why this is the most direct attack on 0086, and not merely another feature.** 0086
tried to win the top-decile by re-ranking on upper predictive quantiles, and it was
flat and then falling (mean 0.516 → P90 0.511 → P99 0.472). The mechanism was
diagnosed and it is worth restating, because it dictates the shape of this module:
**predictive spread came from one *global* residual pool, so it scaled with the level
— the quantiles were nearly a monotone transform of the mean and could not reorder
anything.** Winning a top-decile requires knowing **which constraints are spiky, node
by node, and under what conditions.** A per-constraint sensitivity vector is precisely
that identity, and the model currently has none.

**And it needs no crosswalk at all.** No geocoding, no station names, no centroid, no
namespace to reconcile. We correlate a constraint's own realized μ against each
published zonal/regional forecast over the trailing window, and the constraint tells
us where it lives *in the only currency that matters*: what weather makes it bind.
Commit 3's centroid says where a constraint is in kilometres; this says what it
responds to. **The second is strictly closer to the question.**

**Legal by construction, and the audit cannot see it.** Both sides of every
correlation are backward-only: μ from the closed trailing window, forecasts at their
DAM-close vintage. There is no new feed, no new cutoff, and `audit_leakage` is built
around *vintage* logic — it would have nothing to say about a correlation window that
ran too late, because the columns it inspects are the forecasts' own vintages, which
are already clean. So the window discipline is enforced here, in the walk, and pinned
by `test_wx_window_ends_before_the_history_cutoff` — not delegated to a check that
structurally cannot catch it.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from compute.mu_forecast.features import BIND_DEADBAND
from compute.sf_map.geography import refit_grid

log = logging.getLogger("compute.mu_forecast.weather")

# Same trailing span and cadence as the SF map's fit window. The plan's acceptance
# criterion asks for this explicitly, and the reason is not tidiness: a constraint's
# response to weather is exactly as stationary as its shift factors are, so measuring
# it over a different span would be asserting something about persistence of
# behaviour that nothing else in the project assumes.
from compute.sf_map.config import REFIT_DAYS, WINDOW_DAYS  # noqa: E402

# A window this short cannot support a correlation worth having. Constraints in the
# earliest training margin get NaN instead — a hole, honestly left.
MIN_WINDOW_HOURS = 24 * 28

# The published geography, as ERCOT actually names it. Load is zonal (NP3-561), wind
# and solar are regional (NP4-742 / NP4-745). System-wide totals are deliberately
# EXCLUDED: they are the same number for every constraint, so a correlation against
# them carries no cross-constraint information — which is the only thing this module
# exists to add. `net_load` is kept because it is the physical driver, and a
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


# --------------------------------------------------------------------------
# The correlation
# --------------------------------------------------------------------------

def _zscore(A: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Centre and scale columns; report which ones had any variance at all.

    A constraint that never bound in the window is a constant-zero column: its
    correlation with anything is **undefined, not zero**. Returning 0.0 there would
    tell the model "this constraint is insensitive to load", which is a claim; NaN
    says "we do not know", which is the truth.
    """
    mu = np.nanmean(A, axis=0)
    sd = np.nanstd(A, axis=0)
    ok = sd > 0
    Z = (A - mu) / np.where(ok, sd, 1.0)
    return Z, ok


def response_vectors(M_win: pd.DataFrame, X_win: pd.DataFrame) -> pd.DataFrame:
    """Correlate every constraint's μ against every weather column. One window.

    `M_win` is (hours × constraints) shadow prices, `X_win` is (hours × weather) from
    `system_panel`. Both must already be restricted to the trailing window — this
    function has no notion of time and cannot enforce that, which is why the walk
    below is the only thing that calls it.

    **μ is the magnitude series, zeros included** (|μ| under the bind deadband → 0),
    the same series persistence is made of. Correlating only over *binding* hours
    would answer a different and much less useful question — "given that it bound,
    was it bigger on hot days?" — while the question the model actually needs is
    "does hot weather make this thing bind at all?"
    """
    src = {c: name for c, name in wx_sources().items() if c in X_win.columns}
    if not src:
        return pd.DataFrame(index=M_win.columns)

    hours = M_win.index.intersection(X_win.index)
    if len(hours) < 2:
        return pd.DataFrame(index=M_win.columns)

    mu = M_win.loc[hours].fillna(0.0).abs()
    mu = mu.where(mu > BIND_DEADBAND, 0.0)
    X = X_win.loc[hours, list(src)]

    # Drop hours where any weather column is missing, rather than pairwise-deleting:
    # every constraint must be correlated on the SAME hours, or the response vectors
    # are not comparable across constraints, and comparing them is the entire point.
    keep = X.notna().all(axis=1).to_numpy()
    if keep.sum() < MIN_WINDOW_HOURS:
        return pd.DataFrame(index=M_win.columns)

    Zm, ok_m = _zscore(mu.to_numpy(float)[keep])
    Zx, ok_x = _zscore(X.to_numpy(float)[keep])
    n = int(keep.sum())

    R = (Zm.T @ Zx) / n
    R[~ok_m, :] = np.nan          # never-binding constraint: undefined, not zero
    R[:, ~ok_x] = np.nan          # a flat forecast column: same

    out = pd.DataFrame(np.clip(R, -1.0, 1.0), index=M_win.columns,
                       columns=[src[c] for c in X.columns])
    return out


# --------------------------------------------------------------------------
# The walk — the only caller, and the only place the window is enforced
# --------------------------------------------------------------------------

def wx_panel(M: pd.DataFrame, sys_panel: pd.DataFrame, days: pd.DatetimeIndex,
             window_days: int = WINDOW_DAYS, refit_days: int = REFIT_DAYS,
             anchor: pd.Timestamp | None = None,
             on_refit=None) -> pd.DataFrame:
    """Per (delivery_day, constraint) weather-response vectors, honestly windowed.

    For each refit boundary `s`, the correlations are computed on `[s - window_days,
    s)` — **strictly before `s`** — and used for the delivery days in
    `[s, s + refit_days)`. A delivery day `D` therefore always reads a window whose
    last hour is strictly before `history_cutoff(D)`, which is what the acceptance
    criterion asks for.

    Refit weekly, on the same grid as the SF map (and, when `anchor` is the first
    scored week, in the same phase). Recomputing daily would let a delivery day see
    up to six days more history — legal, but it would put this feature on a different
    cadence from every other fitted thing in the project for no stated reason.
    """
    grid = refit_grid(days, refit_days, anchor)
    cols = [c for c in wx_sources() if c in sys_panel.columns]
    log.info("wx: %d weather columns × %d refit boundaries", len(cols), len(grid))

    frames, skipped = [], 0
    for s in grid:
        s_utc = s.tz_localize("UTC") if s.tzinfo is None else s
        lo_utc = s_utc - pd.Timedelta(days=window_days)

        M_win = M.loc[(M.index >= lo_utc) & (M.index < s_utc)]
        X_win = sys_panel.loc[(sys_panel.index >= lo_utc) & (sys_panel.index < s_utc)]
        if len(M_win) < MIN_WINDOW_HOURS or X_win.empty:
            skipped += 1
            continue

        R = response_vectors(M_win, X_win)
        if R.empty or not R.notna().any().any():
            skipped += 1
            continue

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
