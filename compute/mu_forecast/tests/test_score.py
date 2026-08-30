"""The harness has one job: make the comparison fair. These pin the ways it
could quietly stop being fair."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.evaluation.mu import (
    SOURCES, mu_climatology, mu_from_preds, mu_persistence, report,
    score_matrix, score_week, walk, weeks_from_preds,
)
from compute.sf_map.config import RTC_B

RNG = np.random.default_rng(7)
KEYS = [f"C{i}|X" for i in range(6)]
NODES = [f"SP{i}" for i in range(40)]


def _hours(start: str, days: int) -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(start, tz="UTC"), periods=24 * days,
                         freq="h")


def _world(start="2025-01-01", days=300, sf=None):
    """A synthetic ERCOT: a fixed SF map, sparse binding μ, and the congestion
    that map implies. C is generated FROM M, so a perfect μ source pushed through
    a well-fitted map has to come back with R² ≈ 1 — which is what makes this a
    test of the harness and not of the data."""
    h = _hours(start, days)
    SF = (pd.DataFrame(RNG.normal(0, 0.3, (len(KEYS), len(NODES))),
                       index=KEYS, columns=NODES) if sf is None else sf)
    bind = RNG.random((len(h), len(KEYS))) < 0.12
    M = pd.DataFrame(bind * RNG.gamma(2.0, 20.0, (len(h), len(KEYS))),
                     index=h, columns=KEYS)
    C = pd.DataFrame(-(M.to_numpy() @ SF.to_numpy()), index=h, columns=NODES)
    return M, C, SF


def _preds(M: pd.DataFrame, weeks: pd.DatetimeIndex, mu_col_truth=True):
    """Predictions in `load_preds` shape (already flattened). `mu_col_truth`
    makes the model an oracle in disguise — useful to prove the plumbing carries
    a good μ through to a good score."""
    rows = []
    for s in weeks:
        w = M.loc[(M.index >= s) & (M.index < s + pd.Timedelta(days=7))]
        for k in M.columns:
            v = w[k]
            rows.append(pd.DataFrame({
                "interval_ts": w.index, "key": k, "week": s,
                "p_bind": np.where(v > 0, 1.0, 0.0) if mu_col_truth else 0.05,
                "mu_gbm": v.to_numpy() if mu_col_truth else 30.0,
                "mu_clim": 30.0,
                "y_bind": (v > 0).astype(np.int8),
                "y_mu": v.where(v > 0).to_numpy(),
            }))
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------- the weeks

def test_weeks_are_taken_from_the_preds_not_rederived():
    """The whole point of the harness is 'identical weeks', and the grid has
    already drifted twice in this branch. Reading it off the model's own output
    is what makes drift unrepresentable rather than merely tested-for."""
    M, _, _ = _world()
    weeks = pd.DatetimeIndex([pd.Timestamp("2025-08-14", tz="UTC"),
                              pd.Timestamp("2025-08-21", tz="UTC")])
    got = weeks_from_preds(_preds(M, weeks))
    assert list(got) == list(weeks)


def test_a_misphased_preds_file_is_refused_not_scored():
    """A walk with a broken grid produces a tidy file of the wrong weeks. If it
    ever happens again the harness must stop, not average it."""
    M, _, _ = _world()
    bad = pd.DatetimeIndex([pd.Timestamp("2025-08-14", tz="UTC"),
                            pd.Timestamp("2025-08-22", tz="UTC")])   # 8d apart
    with pytest.raises(ValueError, match="misphased"):
        weeks_from_preds(_preds(M, bad))


def test_a_skipped_week_is_a_hole_not_a_phase_break():
    """`walk_forward` drops a week with too few binders to train on. That leaves a
    14d gap and it is *fine* — the week simply wasn't scored. Only a gap off the
    7d phase means the grid slipped. Refusing an honest hole would be the guard
    being right about the wrong thing."""
    M, _, _ = _world()
    skipped = pd.DatetimeIndex([pd.Timestamp("2025-08-14", tz="UTC"),
                                pd.Timestamp("2025-08-28", tz="UTC")])   # 14d
    assert len(weeks_from_preds(_preds(M, skipped))) == 2


# ------------------------------------------------------------ the sources

def test_oracle_through_the_map_recovers_the_congestion_it_generated():
    """Plumbing check with teeth: C was generated from M through a fixed SF, so
    oracle μ must come back near-perfect. If this sags, the harness is losing
    signal somewhere between the μ matrix and the score, and every other row in
    the table is understated by the same amount."""
    M, C, _ = _world(days=300)
    weeks = pd.DatetimeIndex([pd.Timestamp("2025-10-01", tz="UTC")])
    rows = score_week(M, C, weeks[0], _preds(M, weeks))
    oracle = next(r for r in rows if r["source"] == "oracle")
    assert oracle["rank_spearman"] > 0.95


def test_null_predicts_zero_and_scores_like_it():
    """Null is the floor every other row is read against, so it must actually be
    the floor: zero congestion everywhere, no skill, top-decile at chance.

    Its screening metrics are undefined because a flat map ranks nothing."""
    M, C, _ = _world(days=300)
    weeks = pd.DatetimeIndex([pd.Timestamp("2025-10-01", tz="UTC")])
    rows = score_week(M, C, weeks[0], _preds(M, weeks))
    null = next(r for r in rows if r["source"] == "null")
    # Screening is UNDEFINED for a flat map, not chance-level. Left to the raw
    # metric, argsort's index tie-breaking scored this 0.63 against a 0.10 chance
    # rate — the floor row of the table, inventing skill from column order.
    assert np.isnan(null["topdecile_hit"])
    assert np.isnan(null["rank_spearman"])


def test_persistence_reads_yesterday_not_today():
    """The leak that would flatter persistence into the winner. Give one day a
    signature value and assert it surfaces on the NEXT day, not its own."""
    h = _hours("2025-01-01", 5)
    M = pd.DataFrame(0.0, index=h, columns=KEYS)
    day2 = (M.index >= pd.Timestamp("2025-01-02", tz="UTC")) & \
           (M.index < pd.Timestamp("2025-01-03", tz="UTC"))
    M.loc[day2, KEYS[0]] = 777.0

    hours = h[(h >= pd.Timestamp("2025-01-03", tz="UTC")) &
              (h < pd.Timestamp("2025-01-04", tz="UTC"))]
    p = mu_persistence(M, hours, M.columns)
    assert (p[KEYS[0]] == 777.0).all()           # day 3 sees day 2

    hours2 = h[(h >= pd.Timestamp("2025-01-02", tz="UTC")) &
               (h < pd.Timestamp("2025-01-03", tz="UTC"))]
    assert (mu_persistence(M, hours2, M.columns)[KEYS[0]] == 0.0).all()  # not itself


def test_climatology_is_fitted_on_the_window_only():
    """Poison the scored week; the climatology source must not move. It is fitted
    on the trailing window, and a climatology that has seen the week it grades is
    not a baseline, it is a leak wearing a baseline's name."""
    M, _, _ = _world(days=300)
    s = pd.Timestamp("2025-10-01", tz="UTC")
    M_fit = M.loc[(M.index >= s - pd.Timedelta(days=240)) & (M.index < s)]
    hours = M.loc[(M.index >= s) & (M.index < s + pd.Timedelta(days=7))].index

    before = mu_climatology(M_fit, hours, M.columns)
    M_poisoned = M.copy()
    M_poisoned.loc[hours] = 5000.0
    M_fit2 = M_poisoned.loc[(M_poisoned.index >= s - pd.Timedelta(days=240)) &
                            (M_poisoned.index < s)]
    after = mu_climatology(M_fit2, hours, M.columns)
    pd.testing.assert_frame_equal(before, after)


def test_model_mu_is_the_two_heads_multiplied():
    """E[μ] = P(bind)·E[μ|bind]. Getting this wrong — scoring E[μ|bind] directly
    — would inflate every quiet hour by ~30× and is exactly the kind of error a
    pooled R² reports as 'the model is bad' rather than 'the harness is wrong'."""
    h = _hours("2025-01-01", 1)
    preds = pd.DataFrame({
        "interval_ts": list(h[:2]) * 1, "key": [KEYS[0], KEYS[0]],
        "week": pd.Timestamp("2025-01-01", tz="UTC"),
        "p_bind": [0.5, 0.1], "mu_gbm": [100.0, 200.0], "mu_clim": [10.0, 10.0],
        "y_bind": [1, 0], "y_mu": [np.nan, np.nan],
    })
    got = mu_from_preds(preds, h[:2], pd.Index([KEYS[0]]))
    assert got.iloc[0, 0] == pytest.approx(50.0)     # 0.5 × 100
    assert got.iloc[1, 0] == pytest.approx(20.0)     # 0.1 × 200


def test_keys_the_model_never_saw_are_zero_and_counted():
    """A key with no prediction gets μ=0 — the same implicit treatment the map
    gives a constraint with no column. That is defensible, but it must be
    *visible*: `model_coverage` is what stops a silent hole reading as skill."""
    M, C, _ = _world(days=300)
    s = pd.Timestamp("2025-10-01", tz="UTC")
    preds = _preds(M, pd.DatetimeIndex([s]))
    preds = preds[preds["key"] != KEYS[0]]           # model never saw C0
    rows = score_week(M, C, s, preds)
    assert rows[0]["model_coverage"] < 1.0
    m = mu_from_preds(preds, M.loc[(M.index >= s) &
                                   (M.index < s + pd.Timedelta(days=7))].index,
                      M.columns)
    assert (m[KEYS[0]] == 0.0).all()


# ------------------------------------------------------------- the currencies

def test_screening_metrics_are_always_reported():
    M, C, _ = _world(days=300)
    s = pd.Timestamp("2025-10-01", tz="UTC")
    rows = score_week(M, C, s, _preds(M, pd.DatetimeIndex([s])))
    need = {"rank_spearman", "sign_agree", "topdecile_hit"}
    for r in rows:
        assert need <= set(r), f"{r['source']} is missing {need - set(r)}"
    assert {r["source"] for r in rows} == set(SOURCES)


def test_every_source_is_scored_on_the_same_map_and_the_same_hours():
    """The one thing that must vary between rows is the μ matrix. If two sources
    ever see different hours or different maps, the table is not a comparison."""
    M, C, _ = _world(days=300)
    s = pd.Timestamp("2025-10-01", tz="UTC")
    rows = score_week(M, C, s, _preds(M, pd.DatetimeIndex([s])))
    assert len({r["n_hours"] for r in rows}) == 1
    assert len({r["n_nodes"] for r in rows}) == 1
    assert len({r["n_kept"] for r in rows}) == 1


def test_the_map_is_never_fitted_on_the_week_it_grades():
    """The SF fit ends where the scored week begins — for every source, oracle
    included. An in-sample map is the 0.986 this project already caught itself
    reporting once."""
    M, C, _ = _world(days=300)
    s = pd.Timestamp("2025-10-01", tz="UTC")
    seen = {}

    import compute.evaluation.mu as sc
    real = sc.implied_shift_factors

    def spy(M_fit, C_fit, **kw):
        seen["max_ts"] = M_fit.index.max()
        return real(M_fit, C_fit, **kw)

    sc.implied_shift_factors = spy
    try:
        score_week(M, C, s, _preds(M, pd.DatetimeIndex([s])))
    finally:
        sc.implied_shift_factors = real
    assert seen["max_ts"] < s


def test_report_prints_every_source_and_both_splits():
    """RTC+B is a structural break; a number pooled across it hides a
    regime change. The weeks here straddle it on a real weekly phase."""
    M, C, _ = _world(start="2025-01-01", days=420)
    weeks = pd.date_range(pd.Timestamp("2025-11-13", tz="UTC"), periods=6,
                          freq=pd.Timedelta(days=7))     # 3 pre, 3 post
    df = walk(M, C, _preds(M, weeks))
    txt = report(df)
    for src in SOURCES:
        assert src in txt
    assert "PRE-RTC+B" in txt and "POST-RTC+B" in txt
    assert (df[df["week"] < RTC_B]
            ["week"].nunique()) == 4        # 11-13, 11-20, 11-27, 12-04


def test_a_flat_prediction_cannot_manufacture_a_top_decile():
    """The bug this caught, pinned directly. `argsort` on an all-equal row breaks
    ties by index, so a predictor that says nothing "picks" the first k nodes —
    scoring 0.63 where chance is 0.10. Any future source that goes flat (a map
    with no kept columns, a week the model had nothing for) must read NaN."""
    Y = RNG.normal(size=(24, 40))
    flat = np.zeros((24, 40))
    assert np.isnan(score_matrix(Y, flat)["topdecile_hit"])

    # ...and a source that DOES rank must still be scored, including when only
    # some of its hours are flat.
    half = np.vstack([np.zeros((12, 40)), Y[12:] + RNG.normal(0, .1, (12, 40))])
    assert score_matrix(Y, half)["topdecile_hit"] > 0.5


def test_score_matrix_handles_a_constant_truth_row():
    """A congestion-free hour has zero variance; Spearman is undefined there. It
    must come back NaN and be skipped, not crash the walk 30 weeks in."""
    Y = np.zeros((3, 20))
    Yh = RNG.normal(size=(3, 20))
    m = score_matrix(Y, Yh)
    assert np.isnan(m["rank_spearman"])
