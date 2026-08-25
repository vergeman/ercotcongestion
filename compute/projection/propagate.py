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

from compute.sf_map.config import MIN_HOURS, RIDGE_LAMBDA as LAM, WINDOW_DAYS
STD_FLOOR = 100.0
from compute.sf_map.model.fit import implied_shift_factors
from compute.sf_map.storage.maps import (
    MAP_RUN_ID, MAX_SF_AGE_DAYS, MIN_SF_COVERAGE, load_forecast_sf, load_window_sf,
    resolve_sf_window, sf_mass_coverage,
)
from compute.projection.sampling import (
    DRAW_CHUNK, N_DRAWS, QUANTILES, RESID_CAP, _wide, band_metrics,
    draw_congestion, residual_pool,
)
from compute.projection.codecs import (
    DRIVERS_K, DRIVERS_MAX_DAYS, NodalPanel, SfMuArtifact, _NodalAccumulator,
    build_sf_mu_artifact, load_nodal, load_sf_mu, materialize_drivers,
    node_contributions, node_drivers, parse_curated_days, save_nodal, save_sf_mu,
)

log = logging.getLogger("compute.projection.propagate")





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
