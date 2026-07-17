"""The `forecast_day` production job — fit-then-predict for one delivery day D.

At/after DAM close on D−1, produce the forecast for UTC delivery day D: the nodal
P10/P50/P90 + point panel and the per-day SF+μ artifact. This module is stage-1 +
stage-2 wired end to end **in memory**; persistence and the self-owned pointer flip
are added in the next commit (spec-phase2b §6).

**Why fit-then-predict, not load-and-serve.** The μ-model persists *predictions*,
never fitted boosters (`mu_model.py` has no `joblib.dump`), so there is no weight
file to serve. `forecast_day` refits the heads at run time on the trailing window —
cheap, and honest by construction: `features.py` reads every covariate at its
DAM-close vintage, so tomorrow's panel is fully buildable today (spec §1).

**UTC throughout.** Every `interval_ts` in the DB is a true UTC instant (migration
17), the API speaks UTC, and the model slices the UTC-normalized index — so a
"delivery day" here is a **UTC calendar day** `[D, D+1)` (24 hours, no DST folds),
and `delivery_date = D.date()` (UTC). The DAM-close vintage cutoff in `features.py`
stays a CT wall-clock event; it pins each covariate's publication time per interval
and is independent of this day label (spec §5).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from compute.mu.features import build_panel
from compute.mu.mu_model import DEFAULT_TRAIN_DAYS, load_preds, predict_day
from compute.mu.propagate import (
    N_DRAWS,
    NodalPanel,
    build_sf_mu_artifact,
    propagate_window,
    residual_pool,
)
from compute.mu.score import WINDOW_DAYS
from compute.sf.panels import load_congestion_panel, load_shadow_prices

log = logging.getLogger(__name__)

# The validated backtest's out-of-sample residuals, sampled to form the forward
# error pool (panel spec §7). Module-relative so it resolves regardless of cwd.
PREDS_PATH = os.path.join(os.path.dirname(__file__), "mu_preds.npz")

DEFAULT_ARMS = ("lag", "geo", "wx")      # the shipped `all` config (FEATURE_SETS)


@dataclass
class ForecastResult:
    """One delivery day's forecast, held in memory (nothing written yet).

    `panel` is the nodal P10/P50/P90 + point over D's 24 UTC hours; `SF`/`E_mu` are
    the day's fitted SF map and μ head that `sf_mu` serializes (panel spec §4a).
    `novelty`/`novel_keys` ride along for the run summary — constraints enforced in
    D−1's data that the fit universe never saw bind (spec §7); they are surfaced,
    not fatal.
    """

    run_id: str
    delivery_date: date
    panel: NodalPanel
    SF: pd.DataFrame
    E_mu: pd.DataFrame
    sf_mu: bytes
    novelty: int = 0
    novel_keys: list[str] = field(default_factory=list)


def _as_utc_day(D) -> pd.Timestamp:
    """Normalize any date-ish `D` to a tz-aware UTC midnight — the day boundary the
    whole pipeline slices on (`refit_boundaries`/`predict_day` normalize the same
    way). Rejects a non-midnight instant so a caller can't silently forecast a
    24-hour block offset from the UTC day."""
    ts = pd.Timestamp(D)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts != ts.normalize():
        raise ValueError(f"delivery day must be a UTC midnight boundary, got {ts}")
    return ts.normalize()


def forecast_day(
    conn,
    D,
    *,
    run_id: str,
    train_days: int = DEFAULT_TRAIN_DAYS,
    arms: tuple[str, ...] = DEFAULT_ARMS,
    seed: int = 0,
    n_draws: int = N_DRAWS,
    preds_path: str = PREDS_PATH,
) -> ForecastResult:
    """Fit the heads on the trailing window and forecast UTC delivery day D.

    Two stages (spec §3), reusing the validated fit path and the shared window
    propagator unchanged:

      1. **μ inference** — `build_panel` at the DAM-close vintage over
         `[D−train_days, D+1)`; `predict_day(panel, D)` fits both heads on the
         trailing window and predicts D's 24 hours (`wp`: `p_bind`, `mu_gbm`).
      2. **propagation** — fit the SF map on `[D−WINDOW_DAYS, D)` and draw the nodal
         panel through it via `propagate_window` in forward mode (no realized `Y`,
         hours from D's UTC calendar). The residual pool is the validated backtest's
         out-of-sample errors, strictly before D.

    Reads only; writes nothing and does not touch the pointer (the next commit adds
    persistence). `M`/`C` are loaded over `[D−lookback, D)` **exclusive of D**, so
    no read ever touches an interval ≥ D (spec §5 — the honest path).
    """
    D = _as_utc_day(D)
    lookback = max(train_days, WINDOW_DAYS)
    read_start = D - pd.Timedelta(days=lookback)
    log.info("forecast_day %s  run_id=%s  arms=%s  train_days=%d",
             D.date(), run_id, ",".join(arms), train_days)

    # --- stage 1: μ inference ------------------------------------------------
    # M and C end at D (exclusive): the SF fit window and every covariate see only
    # intervals < D. `score_from=D` phase-locks the geo/wx refit grid so D is itself
    # a boundary — the arm SF for D closes at D, matching the propagation SF below.
    M = load_shadow_prices(conn, read_start, D)
    C = load_congestion_panel(conn, read_start, D) if "geo" in arms else None
    panel = build_panel(conn, M, read_start, D + pd.Timedelta(days=1),
                        C=C, score_from=D,
                        with_weather="wx" in arms,
                        with_outage="outage" in arms)
    if panel.empty:
        raise RuntimeError(f"empty feature panel for {D.date()} — no covariate "
                           f"vintage at DAM close (spec §8: fail, keep pointer)")
    wp = predict_day(panel, D, train_days=train_days, arms=arms, seed=seed)
    novelty = int(wp.attrs.get("novelty", 0))
    novel_keys = list(wp.attrs.get("novel_keys", []))
    log.info("stage 1: panel %s rows, wp %d scored keys, novelty=%d",
             f"{len(panel):,}", wp["key"].nunique() if len(wp) else 0, novelty)

    # --- stage 2: propagation ------------------------------------------------
    rng = np.random.default_rng(seed)
    preds = load_preds(preds_path)
    eps = residual_pool(preds[preds["week"] < D], rng=rng)      # OOS, strictly < D

    # A UTC day is always 24 hours (no DST in UTC). These are D's score-block hours.
    forward_hours = pd.date_range(D, periods=24, freq="h", tz="UTC")
    _, panel_out, SF, E_mu = propagate_window(     # forward mode → no metrics row
        s=D, end=D + pd.Timedelta(days=1), M=M, C=C, wp=wp, eps=eps,
        n_draws=n_draws, rng=rng,
        want_panel=True, want_sf_mu=True, forward_hours=forward_hours)
    if panel_out is None:
        raise RuntimeError(f"propagation produced no panel for {D.date()} — empty "
                           f"SF fit window or empty SF map (spec §8: fail loudly)")
    log.info("stage 2: SF %dx%d, panel %d hours x %d SPs",
             SF.shape[0], SF.shape[1], len(panel_out.ts),
             len(panel_out.settlement_points))

    sf_mu = build_sf_mu_artifact(SF, E_mu)
    return ForecastResult(
        run_id=run_id, delivery_date=D.date(), panel=panel_out,
        SF=SF, E_mu=E_mu, sf_mu=sf_mu,
        novelty=novelty, novel_keys=novel_keys)
