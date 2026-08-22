"""SF projection — push the sampled μ heads through the map and read the bands.

This is the projection library extracted from the old `compute.mu.propagate`
(0095): the math that turns the two μ heads into a nodal distribution through the
shift-factor map, plus the on-disk panel/artifact encodings. It writes nothing to
a DB and owns no CLI — the runners in `compute/jobs/` (`backfill_nodal`,
`daily_forecast`) import it. The verdict/`walk`/DB-write orchestration lives in
`compute.jobs.backfill_nodal`.

The point forecast (commit 4) answers "how sure are you of the number" by turning
the two heads back into the distribution they were always implicitly describing:

    for each draw d:
        bind[k,h] ~ Bernoulli(p_bind[k,h])              # head 1
        μ[k,h]    ~ E[μ|bind][k,h] · exp(ε),  ε ~ residuals   # head 2 + spread
        C[·,h]    = −μ[·,h] · SF                        # the map, unchanged
    P10/P50/P90 = percentiles of C across draws

**Where the spread comes from, and why not from the training window.** Head 2 is a
GBM; its residuals *on its own training window* are the residuals of a model that
has already fitted them, so they are too small, and bands built from them would be
confidently narrow — the exact failure the 0085 summary calls "a confident wrong
band is worse than an honest wide one". Instead the residual pool for week `s` is
the log-space error the model made on **the weeks it already scored, all strictly
before `s`** — genuinely out-of-sample errors, from the same model, on the same
market.

**The known understatement.** Head 1 is sampled independently per constraint. The
constraints are collinear (0083 — that is *why* R3 failed), so the true joint
binding set is far more correlated than independent Bernoullis, and a sum of
independent draws has too thin a tail. This makes coverage a *measurement*, not a
formality: if the bands are too narrow, this is the first place to look.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from compute.mu.score import LAM, MIN_HOURS, STD_FLOOR, WINDOW_DAYS
from compute.sf.fit import implied_shift_factors
from compute.sf.sampling import (
    DRAW_CHUNK, N_DRAWS, QUANTILES, RESID_CAP, _wide, band_metrics,
    draw_congestion, residual_pool,
)
from compute.sf.codecs import (
    DRIVERS_K, DRIVERS_MAX_DAYS, NodalPanel, SfMuArtifact, _NodalAccumulator,
    build_sf_mu_artifact, load_nodal, load_sf_mu, materialize_drivers,
    node_contributions, node_drivers, parse_curated_days, save_nodal, save_sf_mu,
)

log = logging.getLogger("compute.sf.project")

# The forecast reads the map's persisted weekly SF instead of refitting it daily
# (0095-0002). These pin the shared-fit contract:
MAP_RUN_ID = "map-v1"    # the served weekly SF-map run the forecast projects through
MAX_SF_AGE_DAYS = 14     # freshness floor: D − window_end must be ≤ this, else stale.
#   The map refits weekly (REFIT_DAYS), so the freshest complete window closes up to
#   ~a week before D even when current; 14d tolerates one fully missed weekly refresh
#   and fails loud beyond, rather than silently serving weeks-old geography.
MIN_SF_COVERAGE = 0.5    # min share of D's predicted binding MASS the map must locate




# --------------------------------------------------------------------------
# Persisted-SF read + guard (0095-0002) — the forecast projects μ through the
# weekly map's persisted SF instead of refitting SF on [D−240, D) every day.
# --------------------------------------------------------------------------

def resolve_sf_window(conn, run_id: str, *, as_of=None
                      ) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Latest persisted ``(window_start, window_end)`` for ``run_id``, causal to
    ``as_of``.

    Returns the row with the greatest ``window_start`` whose fit closes at or before
    ``as_of`` (``window_end <= as_of``) — the freshest SF a forecast for ``as_of``
    may use without any interval ≥ ``as_of`` entering the fit (``window_end`` is the
    fit-window close, `rolling.py`). ``as_of=None`` drops the causality filter (the
    plain "newest window" the API serves). ``None`` if the run has no window.
    """
    with conn.cursor() as cur:
        if as_of is None:
            cur.execute(
                "SELECT window_start, window_end FROM sf_window_meta "
                "WHERE run_id = %s ORDER BY window_start DESC LIMIT 1", (run_id,))
        else:
            cur.execute(
                "SELECT window_start, window_end FROM sf_window_meta "
                "WHERE run_id = %s AND window_end <= %s "
                "ORDER BY window_start DESC LIMIT 1",
                (run_id, pd.Timestamp(as_of)))
        row = cur.fetchone()
    if row is None:
        return None
    return pd.Timestamp(row[0]), pd.Timestamp(row[1])


def load_window_sf(conn, run_id: str, window_start) -> pd.DataFrame:
    """Read one persisted window's SF matrix (constraint_key × settlement_point).

    The map stores it threshold-sparsified (``|sf| < sf_threshold`` dropped), so an
    absent cell is a true zero: pivot and fill ``0.0`` to hand `draw_congestion` a
    dense matrix on the same axes a fresh fit would. Empty frame if the window has
    no rows.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT constraint_key, settlement_point, sf FROM implied_shift_factors "
            "WHERE run_id = %s AND window_start = %s",
            (run_id, pd.Timestamp(window_start)))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["constraint_key", "settlement_point", "sf"])
    SF = df.pivot_table(index="constraint_key", columns="settlement_point",
                        values="sf", aggfunc="mean").fillna(0.0)
    SF.index.name = None
    SF.columns.name = None
    return SF


def sf_mass_coverage(SF: pd.DataFrame, wp: pd.DataFrame) -> float:
    """Share of D's predicted binding MASS (Σ ``p_bind·mu_gbm``) whose constraint
    the loaded map has a column for.

    Mass-weighted, not a raw key count: a covered key that never binds shouldn't
    prop up coverage, and a novel key that barely binds shouldn't sink it. ``1.0``
    when the day predicts no binding at all (nothing to locate — the degenerate-μ
    guard downstream handles a truly empty forecast)."""
    e_mu = wp["p_bind"].to_numpy(float) * wp["mu_gbm"].to_numpy(float)
    total = float(np.nansum(np.abs(e_mu)))
    if total <= 0:
        return 1.0
    covered = wp["key"].isin(set(SF.index)).to_numpy()
    return float(np.nansum(np.abs(e_mu[covered])) / total)


def load_forecast_sf(conn, D, wp: pd.DataFrame, *, run_id: str = MAP_RUN_ID,
                     max_age_days: int = MAX_SF_AGE_DAYS,
                     min_coverage: float = MIN_SF_COVERAGE) -> pd.DataFrame:
    """Load the weekly map's latest SF for delivery day ``D`` and guard it, or raise.

    Replaces the per-day ``[D−240, D)`` refit: the map already fits this SF weekly
    and persists it (`implied_shift_factors`, run ``run_id``); within the 7-day
    refit interval the model treats SF as stationary, so the freshest complete
    window is valid for ``D``. Causal by construction — only a window with
    ``window_end ≤ D`` is eligible, so the SF never saw an interval ≥ ``D``.

    Fails loud (the caller keeps the prior pointer) on any of: no window built for
    the run; stale (``D − window_end > max_age_days`` — a missed weekly refresh);
    an empty SF matrix; or coverage below ``min_coverage`` of D's predicted binding
    mass (the map universe and D's constraints have diverged).
    """
    D = pd.Timestamp(D)
    win = resolve_sf_window(conn, run_id, as_of=D)
    if win is None:
        raise RuntimeError(
            f"no persisted SF window for run_id={run_id!r} at/before {D.date()} — "
            f"the weekly map ({run_id}) has not been built. Refusing to forecast "
            f"without geography (keep prior pointer).")
    window_start, window_end = win
    age = (D - window_end).days
    if age > max_age_days:
        raise RuntimeError(
            f"stale SF map for {D.date()}: the latest {run_id} window closes "
            f"{window_end.date()} ({age}d old > {max_age_days}d floor). The weekly "
            f"refresh is behind — refusing to serve stale geography (keep pointer).")
    SF = load_window_sf(conn, run_id, window_start)
    if SF.empty:
        raise RuntimeError(
            f"empty SF matrix for {run_id} window {window_start.date()} — nothing "
            f"to project {D.date()} through (keep prior pointer).")
    cov = sf_mass_coverage(SF, wp)
    if cov < min_coverage:
        raise RuntimeError(
            f"low SF coverage for {D.date()}: the {run_id} map locates {cov:.1%} of "
            f"the day's predicted binding mass (< {min_coverage:.0%} floor). The map "
            f"universe and D's constraints have diverged — refusing (keep pointer).")
    log.info("SF from %s window %s (%dd old): %d constraints x %d SPs, coverage %.1f%%",
             run_id, window_start.date(), age, SF.shape[0], SF.shape[1], cov * 100)
    return SF


def propagate_window(
    s: pd.Timestamp, end: pd.Timestamp,
    M: pd.DataFrame, C: pd.DataFrame, wp: pd.DataFrame,
    eps: np.ndarray, n_draws: int, rng: np.random.Generator,
    *, want_panel: bool = False, want_sf_mu: bool = False,
    forward_hours: pd.DatetimeIndex | None = None,
    sf: pd.DataFrame | None = None,
) -> tuple[dict | None, NodalPanel | None, pd.DataFrame | None, pd.DataFrame | None]:
    """One window, shared by the backtest and `forecast_day`.

    Score/draw over ``[s, end)`` and build the weekly-metrics row exactly as
    `walk()` did. The SF map comes from one of two places: fit on
    ``[s−WINDOW_DAYS, s)`` here (``sf=None``, the historic/self-contained path), or
    the persisted weekly map passed in via ``sf`` (0095-0002 — the forecast and the
    backfill both read the map's SF instead of refitting; `load_forecast_sf`
    resolves + guards it). Everything downstream of the SF matrix is identical
    either way.

    Returns ``(row, None, None, None)`` normally; with ``want_panel`` also the
    `NodalPanel` teed from the same draws and the same `np.percentile` call the
    metrics use; with ``want_sf_mu`` also the ``SF`` (K×N) actually used and
    ``E_mu`` (H×K on ``SF.index``) for the SF+μ artifact (§4a). ``(None, None,
    None, None)`` on any skip (empty fit window, empty SF, no scored hours) — the
    caller's `continue`.

    **Forward mode** (`forward_hours` given — `forecast_day` for a delivery day D
    with no realized congestion yet, §3.2): the scored hours are the caller's
    delivery-day calendar (D's 24 intervals) rather than ``M_score ∩ C_score``,
    no realized ``Y`` is read (``C`` is never indexed on the score side, so a
    ``C`` that is empty/absent for D cannot crash the panel), and ``row`` is
    ``None`` (no `band_metrics` without an outcome). The `want_panel`/`want_sf_mu`
    tees are byte-identical to the backtest.
    """
    forward = forward_hours is not None
    if sf is None:
        lo, hi = s - pd.Timedelta(days=WINDOW_DAYS), s
        M_fit = M.loc[(M.index >= lo) & (M.index < hi)]
        C_fit = C.loc[(C.index >= lo) & (C.index < hi)]
        if M_fit.empty:
            return None, None, None, None
        SF = implied_shift_factors(M_fit, C_fit, lam=LAM, min_hours=MIN_HOURS,
                                   standardize=True, std_floor=STD_FLOOR)
    else:
        SF = sf                             # persisted weekly map (already guarded)
    if SF.empty:
        return None, None, None, None

    M_score = M.loc[(M.index >= s) & (M.index < end)]
    if forward:
        hours = forward_hours
    else:
        C_score = C.loc[(C.index >= s) & (C.index < end)]
        hours = M_score.index.intersection(C_score.index)
        # The persisted SF was fit on a 240-day window that can include settlement
        # points retired/renamed before this scored week — they are simply absent
        # from the congestion panel here. Drop them: a node the SP data no longer
        # carries can be neither realized (graded) nor honestly projected. (Forward
        # mode never indexes C on the score side, so it keeps the full map.)
        absent = SF.columns.difference(C_score.columns)
        if len(absent):
            log.info("week %s: dropping %d SP(s) absent from congestion panel "
                     "(retired/renamed, e.g. %s)", s.date(), len(absent),
                     ", ".join(map(str, absent[:3])))
            SF = SF.loc[:, SF.columns.intersection(C_score.columns)]
            if SF.empty:
                return None, None, None, None
    if not len(hours):
        return None, None, None, None

    wp = wp[wp["key"].isin(SF.index)]

    mass_all = float(M_score.abs().to_numpy(float).sum())
    cov_cols = M_score.columns.intersection(SF.index)
    sf_coverage = (float(M_score[cov_cols].abs().to_numpy(float).sum())
                   / mass_all if mass_all > 0 else np.nan)

    panel = None
    if want_panel:
        draws, point = draw_congestion(wp, SF, hours, eps, n_draws, rng,
                                       want_point=True)
        p10, p50, p90 = np.percentile(draws, QUANTILES, axis=0)
        panel = NodalPanel(
            ts=hours.to_numpy(),
            settlement_points=SF.columns.to_numpy(),
            p10=p10.astype(np.float32), p50=p50.astype(np.float32),
            p90=p90.astype(np.float32), point=point,
            sf_r2=None,          # implied_shift_factors exposes no per-SP R² (§11)
        )
    else:
        draws = draw_congestion(wp, SF, hours, eps, n_draws, rng)
        p10, p50, p90 = np.percentile(draws, QUANTILES, axis=0)

    E_mu = None
    if want_sf_mu:
        # E[μ]=P(bind)·E[μ|bind] on SF.index — the same arrays draw_congestion builds
        # (§4a), rebuilt here (two cheap pivots) so the return needs no draws.
        P = _wide(wp, "p_bind", hours, SF.index)
        MU = _wide(wp, "mu_gbm", hours, SF.index)
        E_mu = pd.DataFrame(P * MU, index=hours, columns=SF.index)

    row = None
    if not forward:
        # hours ⊆ C_score.index ⊆ C.index, so this selects the same rows in the
        # same order as the pre-forward `C_score.loc[hours]`, byte-identical.
        Y = C.loc[hours, SF.columns].to_numpy(np.float32)
        row = {"week": s, "n_hours": len(hours), "n_nodes": SF.shape[1],
               "n_resid": len(eps), "sf_coverage": sf_coverage,
               **band_metrics(Y, p10, p50, p90)}
    return row, panel, (SF if want_sf_mu else None), E_mu
