"""A post-hoc test has one job before it is allowed to report anything: prove it
could have found the effect it is looking for. A re-rank that cannot detect a
quantile effect on a fixture where one is planted by construction has not refuted
the hypothesis — it has failed to test it, which reads identically and is not."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.mu.rerank import STATS, rank_stats, score_ranking, verdict

RNG = np.random.default_rng(7)


def test_the_six_readings_are_the_same_cube_not_six_models():
    """Nothing is refitted. Every stat must be a summary of the SAME draws, and
    they must be ordered — if p90 ever sits below p50 the percentile axis is wrong
    and every number downstream is noise."""
    draws = RNG.normal(0, 5, (200, 24, 30))
    s = rank_stats(draws)
    assert set(s) == set(STATS)
    assert (s["p50"] <= s["p75"]).all()
    assert (s["p75"] <= s["p90"]).all()
    assert (s["p90"] <= s["p99"]).all()
    np.testing.assert_allclose(s["mean"], draws.mean(axis=0), rtol=1e-6)


def test_a_symmetric_forecast_gives_the_quantiles_nothing_to_find():
    """The null case. If every node has the SAME spread, an upper quantile is just
    the mean plus a constant — it cannot reorder anything, so top-decile must be
    unchanged. This is what a REFUTED result should look like, and pinning it is
    what stops us reading noise as a discovery."""
    H, N = 60, 40
    truth = RNG.normal(0, 10, (H, N))
    centre = truth + RNG.normal(0, 3, (H, N))
    # identical spread on every node ⇒ a rigid shift, not a re-ranking
    draws = centre[None] + RNG.normal(0, 4, (200, 1, 1)) * np.ones((1, H, N))

    s = rank_stats(draws)
    assert (score_ranking(truth, s["p90"])["topdecile_hit"]
            == pytest.approx(score_ranking(truth, s["mean"])["topdecile_hit"],
                             abs=1e-9))


def test_the_rerank_can_actually_find_a_planted_quantile_effect():
    """The power check, and the reason this file exists. Without it, a flat result
    on real data cannot be told apart from a harness that is simply blind.

    Build the world the hypothesis describes exactly: every node has the **same
    mean** (`P(bind) · E[μ|bind] = 50`) and a **different spread** — a certain $50
    at one end, a 40%-chance-of-$125 at the other. The mean is definitionally
    unable to separate them. But only the spiky ones ever appear in a *realized*
    top decile, and an upper quantile ranks by exactly the spread the mean threw
    away. If the harness cannot recover that here, it cannot recover it anywhere.
    """
    H, N, D = 400, 50, 400
    pi = np.geomspace(0.40, 1.0, N)          # bind probability, low → certain
    S = 50.0 / pi                            # magnitude, so that pi·S ≡ 50

    truth = (RNG.random((H, N)) < pi) * S + RNG.normal(0, 1, (H, N))
    draws = (RNG.random((D, H, N)) < pi) * S + RNG.normal(0, 1, (D, H, N))

    td = {k: score_ranking(truth, v)["topdecile_hit"]
          for k, v in rank_stats(draws).items()}
    best_upper = max(td[q] for q in ("p75", "p90", "p95", "p99"))

    assert best_upper > td["mean"] + 0.15, (
        f"harness is blind to a planted quantile effect: mean {td['mean']:.3f}, "
        f"best upper {best_upper:.3f} — a null result on real data would be "
        f"meaningless")


def test_the_useful_quantile_is_not_assumed_to_be_the_highest_one():
    """Guards a mistake I nearly shipped: I assumed P90 was *the* re-rank and would
    have tested only that.

    An upper quantile can over-extrapolate. Ranking by P99 prefers a
    1%-chance-of-$10,000 node over a 40%-chance-of-$300 one, which is the wrong
    call for a *top-decile* question. So the sweep must span the middle — and on a
    world with genuinely rare binders, P75 beats P90. Pinning that stops the next
    reader from quietly dropping the interior quantiles as redundant.
    """
    H, N, D = 400, 50, 400
    pi = np.geomspace(0.05, 1.0, N)          # some binders are genuinely rare
    S = 50.0 / pi
    truth = (RNG.random((H, N)) < pi) * S + RNG.normal(0, 1, (H, N))
    draws = (RNG.random((D, H, N)) < pi) * S + RNG.normal(0, 1, (D, H, N))

    td = {k: score_ranking(truth, v)["topdecile_hit"]
          for k, v in rank_stats(draws).items()}
    assert td["p75"] > td["p90"] > td["p99"]
    assert "p75" in STATS and "p95" in STATS


def test_a_quantile_ranking_is_not_graded_on_magnitude():
    """P90 is a deliberately biased estimate of the price — it is not trying to be
    the price. Scoring it with R² would penalise it for a job it is not applying
    for, so the screening currency is all it reports."""
    m = score_ranking(RNG.normal(0, 5, (30, 25)), RNG.normal(0, 5, (30, 25)))
    assert set(m) == {"rank_spearman", "sign_agree", "topdecile_hit"}
    assert "pooled_r2" not in m


def test_the_verdict_reads_the_bar_as_written():
    """CONFIRMED requires BOTH: beat persistence's top-decile AND keep the rank.
    A quantile that buys the tail by wrecking the ranking is a different failure,
    not a success, and the verdict must say so."""
    weeks = pd.date_range("2025-08-21", periods=3, freq="7D", tz="UTC")
    scores = pd.DataFrame([
        {"week": w, "source": src, "regime": "all", "rank_spearman": sp,
         "sign_agree": sg, "topdecile_hit": td}
        for w in weeks
        for src, sp, sg, td in [("persistence", 0.496, 0.736, 0.561),
                                ("model", 0.548, 0.787, 0.523)]])

    def rr(td_by_stat, sp=0.55):
        return pd.DataFrame([{"week": w, "stat": st, "rank_spearman": sp,
                              "sign_agree": 0.79, "topdecile_hit": td}
                             for w in weeks for st, td in td_by_stat.items()])

    flat = {s: 0.523 for s in STATS}
    assert "REFUTED" in verdict(rr(flat), scores)

    lifted = {**flat, "p90": 0.640}
    assert "CONFIRMED" in verdict(rr(lifted), scores)

    # wins the tail, but hands back the rank correlation ⇒ still refuted
    assert "REFUTED" in verdict(rr(lifted, sp=0.40), scores)
