"""every μ source, one harness, identical weeks.

does a covariate μ-model beat the naive baselines once you push it through the
SF map:

Every source, oracle included, is re-measured here: same weeks, same SF fit,
same metric functions, one loop. The only thing that varies from row to row is
the μ matrix handed to the map.

The weeks are taken from the predictions file, not re-derived.

The scoreboard uses rank-Spearman (cross-node, per hour), sign agreement (±$1
deadband), and top-decile hit.

    docker compose run --rm compute python -m compute.evaluation.mu \
      --preds /tmp/predictions.npz --out /tmp/scores.csv

"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from compute.evaluation.sf import predict
from compute.metrics import screening_metrics
from compute.sf_map.model.fit import implied_shift_factors

log = logging.getLogger("compute.evaluation.mu")

# The adopted operating point single-sourced in `compute.sf_map.config` so the
# μ forecast and the SF map cannot drift.
from compute.sf_map.config import (  # noqa: E402
    MIN_HOURS, REFIT_DAYS, RIDGE_LAMBDA as LAM, RTC_B, WINDOW_DAYS,
)
STD_FLOOR = 100.0


@dataclass(frozen=True)
class SourceDefinition:
    """Compute-owned identity and construction for one μ evaluation source."""

    id: str
    series_id: str
    label: str
    definition: str
    constructor: str


SOURCE_DEFINITIONS = (
    SourceDefinition("compute_mu_model_walk_forward", "model", "Model",
                         "Walk-forward E[μ] from the fitted μ model.", "model"),
    SourceDefinition("compute_mu_persistence_prior_day", "persistence", "Persistence",
                         "Same hour of the prior settled day.", "persistence"),
    SourceDefinition("compute_mu_climatology_hourly", "climatology", "Climatology",
                         "Hourly P(bind) × E[μ | bind] over the fit window.", "climatology"),
    SourceDefinition("compute_mu_oracle_realized", "oracle", "Oracle",
                         "Realized μ, projected through the held-out map.", "oracle"),
    SourceDefinition("compute_mu_null_zero", "null", "Null",
                         "Flat zero-μ tripwire.", "null"),
)
SOURCE_BY_ID = {source.id: source for source in SOURCE_DEFINITIONS}
SOURCE_IDS = tuple(source.id for source in SOURCE_DEFINITIONS)


# --------------------------------------------------------------------------
# μ sources — the only thing that varies between rows
# --------------------------------------------------------------------------
# `mu_persistence` and `mu_climatology` are lifted verbatim from the frozen
# `experiments/sf_out_of_window/common.py`.

def mu_persistence(M: pd.DataFrame, hours: pd.DatetimeIndex,
                   cols: pd.Index) -> pd.DataFrame:
    """Same hour-of-day, previous day.

    Admissible at the 10:00 DAM close on D-1: the shadow prices for **all 24
    hours** of D-1 were cleared and published on D-2. This is the D-1 rule that
    `features.py` pins from both sides — being cautious here and lagging 48h
    would throw away the freshest signal we have, for nothing.
    """
    prev = M.reindex(hours - pd.Timedelta(days=1))
    out = prev.reindex(columns=cols).fillna(0.0)
    out.index = hours
    return out


def mu_climatology(M_fit: pd.DataFrame, hours: pd.DatetimeIndex,
                   cols: pd.Index) -> pd.DataFrame:
    """P(bind | hour-of-day) × mean(μ | binding), both estimated on the fit
    window ONLY. The pivot doc's "conditional historical mean".

    Note this is *not* head 2's climatology: head 2's is E[μ | bind] bucketed on
    net load, a conditional severity model. This one is an unconditional expected
    μ — it carries its own P(bind), because as a μ *source* it has to stand alone.
    """
    Mf = M_fit.reindex(columns=cols).fillna(0.0)
    binding = Mf > 0
    mean_given_bind = Mf.where(binding).mean().fillna(0.0)
    p_bind = binding.groupby(Mf.index.hour).mean()
    vals = (p_bind.reindex(pd.Index(hours).hour).to_numpy(float)
            * mean_given_bind.to_numpy(float)[None, :])
    return pd.DataFrame(vals, index=hours, columns=cols)


def mu_from_preds(week_preds: pd.DataFrame, hours: pd.DatetimeIndex,
                  cols: pd.Index, mu_col: str = "mu_gbm") -> pd.DataFrame:
    """The model's μ: **E[μ] = P(bind) · E[μ | bind]** — the two heads multiplied.

    This is the point estimate a squared-error currency asks for, and it is the
    reason the heads were split in the first place: a single regressor over all
    hours would have learned to say "about zero" (the base rate is 3%), which is
    right on average and useless in every hour anyone cares about.

    Keys the model never saw get 0.0 — the same implicit treatment the SF map
    gives a constraint it has no column for. `score_week` reports the μ-mass that
    lands on those keys so the silence is visible rather than absorbed.
    """
    mu = (week_preds["p_bind"].to_numpy(float)
          * week_preds[mu_col].to_numpy(float))
    wide = pd.DataFrame({"interval_ts": week_preds["interval_ts"].to_numpy(),
                         "key": week_preds["key"].to_numpy(), "mu": mu})
    wide = wide.pivot_table(index="interval_ts", columns="key", values="mu",
                            aggfunc="mean")
    return wide.reindex(index=hours, columns=cols).fillna(0.0)


def mu_null(hours: pd.DatetimeIndex, cols: pd.Index) -> pd.DataFrame:
    """Predict zero congestion."""
    return pd.DataFrame(0.0, index=hours, columns=cols)


def weeks_from_preds(preds: pd.DataFrame) -> pd.DatetimeIndex:
    """The scored weeks, **read off the model's own output**.

    """
    weeks = pd.DatetimeIndex(sorted(preds["week"].unique()))
    gaps = weeks.to_series().diff().dropna()
    off = gaps[(gaps % pd.Timedelta(days=REFIT_DAYS)) != pd.Timedelta(0)]
    if len(off):
        raise ValueError(
            f"preds weeks are off the {REFIT_DAYS}d grid: gaps {sorted(set(off))} "
            f"— the walk that produced this file was misphased, refusing to score it")
    return weeks

# --------------------------------------------------------------------------
# backtest
# only used in this main() and compute/experiment scripts
# --------------------------------------------------------------------------

def score_week(M: pd.DataFrame, C: pd.DataFrame, s: pd.Timestamp,
               week_preds: pd.DataFrame, window_days: int = WINDOW_DAYS,
               refit_days: int = REFIT_DAYS,
               lam: float = LAM) -> list[dict]:
    """This is inactive and backtest-only; was used to grade historic data prior
     to regular daily forecast job.

    the window ends exactly where the scored week begins, so no source —
    including oracle — is scored by a map that has seen the week it is being
    graded on.

    """
    lo, hi = s - pd.Timedelta(days=window_days), s
    end = s + pd.Timedelta(days=refit_days)

    M_fit, C_fit = M.loc[(M.index >= lo) & (M.index < hi)], C.loc[(C.index >= lo) & (C.index < hi)]
    if M_fit.empty:
        return []
    SF = implied_shift_factors(M_fit, C_fit, lam=lam, min_hours=MIN_HOURS,
                               standardize=True, std_floor=STD_FLOOR)
    if SF.empty:
        return []

    M_score = M.loc[(M.index >= s) & (M.index < end)]
    C_score = C.loc[(C.index >= s) & (C.index < end)]
    hours = M_score.index.intersection(C_score.index)
    if not len(hours):
        return []
    M_score, C_score = M_score.loc[hours], C_score.loc[hours]
    cols = M_score.columns

    # SF coverage: the scored week's |μ|-mass that the map has a column for.
    mass_all = float(M_score.abs().to_numpy(float).sum())
    in_cols = cols.intersection(SF.index)
    sf_coverage = (float(M_score[in_cols].abs().to_numpy(float).sum()) / mass_all
                   if mass_all > 0 else np.nan)

    # The model's OWN coverage, which is a different hole: keys it has no
    # prediction for (never in the covariate panel) are silently zero.
    pred_keys = cols.intersection(pd.Index(week_preds["key"].unique()))
    model_coverage = (float(M_score[pred_keys].abs().to_numpy(float).sum()) / mass_all
                      if mass_all > 0 else np.nan)

    srcs: dict[str, pd.DataFrame] = {
        "compute_mu_oracle_realized": M_score,
        "compute_mu_model_walk_forward": mu_from_preds(week_preds, hours, cols, "mu_gbm"),
        "compute_mu_climatology_hourly": mu_climatology(M_fit, hours, cols),
        "compute_mu_persistence_prior_day": mu_persistence(M, hours, cols),
        "compute_mu_null_zero": mu_null(hours, cols),
    }
    Y = C_score[SF.columns].to_numpy(float)

    rows: list[dict] = []
    for name, Msrc in srcs.items():
        Yh = predict(Msrc, SF)
        base = {"week": s, "source": name, "n_hours": len(hours),
                "n_nodes": SF.shape[1], "n_kept": SF.shape[0],
                "sf_coverage": sf_coverage, "model_coverage": model_coverage,
                **screening_metrics(Y, Yh)}
        rows.append(base)
    return rows


def walk(M: pd.DataFrame, C: pd.DataFrame, preds: pd.DataFrame,
         window_days: int = WINDOW_DAYS,
         refit_days: int = REFIT_DAYS, lam: float = LAM) -> pd.DataFrame:
    """This is inactive and backtest-only; was used to grade historic data prior
     to regular daily forecast job.

    """
    # `load_preds` hands back a (interval_ts, key) MultiIndex; the sources want
    # them as columns.
    if isinstance(preds.index, pd.MultiIndex):
        preds = preds.reset_index()

    weeks = weeks_from_preds(preds)
    log.info("scoring %d weeks [%s → %s] × %d sources, window=%dd λ=%g",
             len(weeks), weeks[0].date(), weeks[-1].date(),
             len(SOURCE_IDS), window_days, lam)

    by_week = dict(tuple(preds.groupby("week", sort=False)))
    rows: list[dict] = []
    t0 = time.perf_counter()
    for i, s in enumerate(weeks):
        rows.extend(score_week(M, C, s, by_week[s], window_days,
                               refit_days, lam))
        done, el = i + 1, time.perf_counter() - t0
        log.info("  week %2d/%d %s  eta %.0fm", done, len(weeks), s.date(),
                 (el / done) * (len(weeks) - done) / 60)
    return pd.DataFrame(rows)


def evaluate_predictions(conn, preds: pd.DataFrame, *, end: pd.Timestamp,
                         window_days: int = WINDOW_DAYS, lam: float = LAM,
                         ) -> pd.DataFrame:
    """Load the causal evaluation inputs and score an in-memory μ walk."""
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices

    weeks = weeks_from_preds(preds.reset_index() if isinstance(preds.index, pd.MultiIndex)
                             else preds)
    if not len(weeks):
        return pd.DataFrame()
    lo = weeks[0] - pd.Timedelta(days=window_days)
    M = load_shadow_prices(conn, lo, end)
    C = load_congestion_panel(conn, lo, end)
    try:
        return walk(M, C, preds, window_days, REFIT_DAYS, lam)
    finally:
        del M, C


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def _table(df: pd.DataFrame, title: str, order: list[str]) -> str:
    out = [f"\n{title}",
           f"  {'μ source':<14} {'Spearman':>9} "
           f"{'sign':>7} {'top-dec':>8}   {'weeks':>5}"]
    for src in order:
        d = df[df["source"] == src]
        if d.empty:
            continue
        out.append(f"  {src:<14} {d.rank_spearman.mean():>9.3f} "
                   f"{d.sign_agree.mean():>7.3f} {d.topdecile_hit.mean():>8.3f}"
                   f"   {len(d):>5}")
    return "\n".join(out)


def report(df: pd.DataFrame) -> str:
    """All-hours screening metrics, with the RTC+B split."""
    order = [source.id for source in SOURCE_DEFINITIONS
             if (df["source"] == source.id).any()]
    a = df
    out = [_table(a, "=== ALL WEEKS (screening) ===", order)]

    pre, post = a[a["week"] < RTC_B], a[a["week"] >= RTC_B]
    out.append(_table(pre, f"=== PRE-RTC+B (< {RTC_B.date()}) ===", order))
    out.append(_table(post, f"=== POST-RTC+B (≥ {RTC_B.date()}) ===", order))

    out.append(f"\n  SF coverage {a.sf_coverage.mean():.3f}   "
               f"model key-coverage {a.model_coverage.mean():.3f}   "
               f"(scored-week |μ|-mass with a column / with a prediction)")
    out.append("  top-decile by chance = 0.100.  null's screening cells are NaN "
               "by design: a flat map ranks nothing.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import psycopg

    from compute.mu_forecast.model.runner import load_preds
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--preds", required=True)
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    p.add_argument("--lam", type=float, default=LAM)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    preds = load_preds(args.preds)
    log.info("preds = %s rows, %d weeks", f"{len(preds):,}",
             preds["week"].nunique())

    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    with psycopg.connect(dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)
        log.info("M = %s   C = %s", M.shape, C.shape)
    df = walk(M, C, preds, args.window_days, REFIT_DAYS, args.lam)
    if df.empty:
        print("no scorable weeks")
        return 1

    print(report(df))
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
