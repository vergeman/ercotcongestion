"""0086 — a POST-HOC question, asked after R5 failed. It cannot un-fail it.

**The observation.** In commit 5 the model beat persistence on every measure that
rewards being right *on average* (R² +0.221 vs −0.013, Spearman 0.548 vs 0.496,
sign 0.787 vs 0.736) and lost the single measure that asks it to *point at the
extremes* (top-decile 0.524 vs 0.561). That is a suspicious pattern, and there is
a mechanical reason it might arise that has nothing to do with the model's skill.

**The hypothesis.** We rank nodes by `E[μ] = P(bind) · E[μ|bind]` — a *mean*. A
constraint with a 20% chance of a $400 bind contributes $80, the same as a
certain $80 bind, and the map smears those two into the same nodal number. But
they are not the same claim, and the top-decile metric only cares about the first
one. Persistence, meanwhile, ranks by *yesterday's realized* congestion — a draw
from the tail, sharp and un-smeared. So we may be losing a tail metric because we
are ranking it with a central statistic, not because we know less than yesterday.

If so, the fix is not a model, it is a *decision rule*: rank by an upper quantile
of the predictive distribution — "where could this plausibly go badly" — rather
than by its middle. We already draw that distribution in `propagate.py`; this
module only re-reads it.

**Pre-registered, before the run:**

  * The hypothesis is CONFIRMED iff some upper quantile beats persistence's
    top-decile **on the identical weeks** *without* giving back the Spearman the
    mean ranking already wins. Winning top-decile by wrecking the ranking is not
    a win, it is a different failure.
  * The hypothesis is REFUTED iff top-decile is flat or falls as the quantile
    rises. Then the missing-outage-data story (0086 summary) is the whole story.
  * **Either way §5.5 is unmoved.** The screening bar wants Spearman ≥ 0.60 AND
    top-decile ≥ 0.60. Even a clean confirmation here does not clear it, and the
    R5 verdict recorded in 0085 stands. This decides *where the skill went*, not
    *whether we have a product*.

`mean` is included as the control: it should reproduce commit 4's 0.523, and if
it does not, this harness is wrong and nothing below it means anything.

    docker compose run --rm compute python -m compute.experiments.mu.rerank \
      --preds /compute/runs/mu-all-v1/mu/mu_preds.npz \
      --scores /compute/runs/mu-all-v1/mu/mu_score_weekly.csv \
      --out /compute/runs/experiments/mu/mu_rerank_weekly.csv
"""
from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from compute.projection.sampling import draw_congestion, residual_pool
from compute.evaluation.mu import (
    LAM, MIN_HOURS, REFIT_DAYS, STD_FLOOR, WINDOW_DAYS,
    topdecile_hit_defined, weeks_from_preds,
)
from compute.evaluation.sf import row_spearman, sign_agreement
from compute.sf_map.model.fit import implied_shift_factors

log = logging.getLogger("compute.experiments.mu.rerank")

# The middle, and four progressively more pessimistic readings of the same draws.
STATS = ("mean", "p50", "p75", "p90", "p95", "p99")


def rank_stats(draws: np.ndarray) -> dict[str, np.ndarray]:
    """The same (draws × hours × nodes) cube, read six ways.

    Every one of these is a legitimate summary of the *same* forecast — nothing
    is refitted, nothing new is learned. Only the question changes, from "what do
    we expect" to "how bad could this reasonably get".
    """
    qs = [50, 75, 90, 95, 99]
    p = np.percentile(draws, qs, axis=0)
    out = {"mean": draws.mean(axis=0)}
    out.update({f"p{q}": p[i] for i, q in enumerate(qs)})
    return out


def score_ranking(Y: np.ndarray, Yh: np.ndarray) -> dict:
    """Screening currency only. A quantile ranking is deliberately *biased* as a
    magnitude estimate — P90 is not trying to be the price, so grading it with R²
    would be scoring it on a job it is not applying for."""
    return {
        "rank_spearman": row_spearman(Y, Yh),
        "sign_agree": sign_agreement(Y, Yh),
        "topdecile_hit": topdecile_hit_defined(Y, Yh),
    }


def walk(M: pd.DataFrame, C: pd.DataFrame, preds: pd.DataFrame,
         n_draws: int = 200, seed: int = 0) -> pd.DataFrame:
    """`propagate.walk`, but scoring six readings of the cube instead of one.

    Deliberately re-derived from the same inputs with the same seed rather than
    cached from commit 5: the weeks, the map, the residual pool and the draws must
    be *identical* to the ones the R5 verdict was read off, or this is a
    comparison between two experiments and not between two ranking rules.
    """
    if isinstance(preds.index, pd.MultiIndex):
        preds = preds.reset_index()
    weeks = weeks_from_preds(preds)
    rng = np.random.default_rng(seed)
    by_week = dict(tuple(preds.groupby("week", sort=False)))

    rows: list[dict] = []
    t0 = time.perf_counter()
    for i, s in enumerate(weeks):
        prior = preds[preds["week"] < s]
        eps = residual_pool(prior, rng=rng)
        if not len(eps):
            continue                       # week 1: no pool, no draws, no bands

        lo, hi = s - pd.Timedelta(days=WINDOW_DAYS), s
        end = s + pd.Timedelta(days=REFIT_DAYS)
        M_fit = M.loc[(M.index >= lo) & (M.index < hi)]
        C_fit = C.loc[(C.index >= lo) & (C.index < hi)]
        if M_fit.empty:
            continue
        SF = implied_shift_factors(M_fit, C_fit, lam=LAM, min_hours=MIN_HOURS,
                                   standardize=True, std_floor=STD_FLOOR)
        if SF.empty:
            continue

        M_score = M.loc[(M.index >= s) & (M.index < end)]
        C_score = C.loc[(C.index >= s) & (C.index < end)]
        hours = M_score.index.intersection(C_score.index)
        if not len(hours):
            continue

        wp = by_week[s]
        wp = wp[wp["key"].isin(SF.index)]
        draws = draw_congestion(wp, SF, hours, eps, n_draws, rng)
        Y = C_score.loc[hours, SF.columns].to_numpy(np.float32)

        for name, Yh in rank_stats(draws).items():
            rows.append({"week": s, "stat": name, "n_hours": len(hours),
                         **score_ranking(Y, Yh)})
        done, el = i + 1, time.perf_counter() - t0
        td = {r["stat"]: r["topdecile_hit"] for r in rows[-len(STATS):]}
        log.info("  week %2d/%d %s  top-dec mean %.3f  p90 %.3f  p99 %.3f  eta %.0fm",
                 done, len(weeks), s.date(), td["mean"], td["p90"], td["p99"],
                 (el / done) * (len(weeks) - done) / 60)
    return pd.DataFrame(rows)


def verdict(rr: pd.DataFrame, scores: pd.DataFrame) -> str:
    """Read against the bar written at the top of this file, on identical weeks."""
    weeks = sorted(rr["week"].unique())
    a = scores[(scores["regime"] == "all") & (scores["week"].isin(weeks))]

    def base(src: str) -> dict:
        d = a[a["source"] == src]
        return {k: float(d[k].mean())
                for k in ("rank_spearman", "sign_agree", "topdecile_hit")}

    pers, model = base("persistence"), base("model")
    out = ["\n=== 0086 — is the model losing top-decile because we rank it by a MEAN? ===",
           f"    {len(weeks)} weeks (week 1 has no residual pool), identical to the "
           f"R5 bands walk\n",
           f"  {'ranking rule':<14} {'Spearman':>9} {'sign':>7} {'top-decile':>11}   vs persistence",
           f"  {'-' * 62}",
           f"  {'persistence':<14} {pers['rank_spearman']:>9.3f} "
           f"{pers['sign_agree']:>7.3f} {pers['topdecile_hit']:>11.3f}   —  the bar",
           f"  {'model (mean)':<14} {model['rank_spearman']:>9.3f} "
           f"{model['sign_agree']:>7.3f} {model['topdecile_hit']:>11.3f}   "
           f"{'WIN' if model['topdecile_hit'] > pers['topdecile_hit'] else 'LOSS'}"
           f"  ← what R5 graded"]

    best, best_td = None, -np.inf
    for st in STATS:
        d = rr[rr["stat"] == st]
        sp, sg = float(d.rank_spearman.mean()), float(d.sign_agree.mean())
        td = float(d.topdecile_hit.mean())
        beats = td > pers["topdecile_hit"]
        keeps = sp >= model["rank_spearman"] - 0.005     # didn't give back the rank
        out.append(f"  {'draws ' + st:<14} {sp:>9.3f} {sg:>7.3f} {td:>11.3f}   "
                   f"{'WIN ' if beats else 'LOSS'}"
                   f"{'' if keeps else '  (rank given back)'}")
        if beats and keeps and td > best_td:
            best, best_td = st, td

    out += ["", f"  {'-' * 62}"]
    if best:
        out += [f"  CONFIRMED — ranking by `{best}` beats persistence's top-decile "
                f"({best_td:.3f} vs {pers['topdecile_hit']:.3f}) without giving back",
                "  the rank correlation. The model was not blinder than yesterday; we "
                "were reading",
                "  it with the wrong statistic. §5.5 is UNMOVED (screening still wants "
                "Spearman",
                "  ≥ 0.60 AND top-decile ≥ 0.60) and the R5 verdict in 0085 STANDS."]
    else:
        out += ["  REFUTED — no upper quantile buys back the top-decile. The mean was "
                "not the",
                "  problem. The model genuinely knows less than yesterday about where "
                "the",
                "  extremes land, and the missing-outage-data story is the whole story."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import psycopg

    from compute.mu_forecast.model.runner import load_preds
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--preds", default="/compute/runs/mu-all-v1/mu/mu_preds.npz")
    p.add_argument("--scores", default="/compute/runs/mu-all-v1/mu/mu_score_weekly.csv")
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--draws", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)      # same seed as commit 5
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    preds = load_preds(args.preds)
    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    with psycopg.connect(dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)
    log.info("M = %s   C = %s", M.shape, C.shape)

    rr = walk(M, C, preds, args.draws, args.seed)
    scores = pd.read_csv(args.scores, parse_dates=["week"])
    print(verdict(rr, scores))
    if args.out and not rr.empty:
        rr.to_csv(args.out, index=False)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
