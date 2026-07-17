"""The two heads (plan/0085 commit 3).

The risk here is not that the GBM is bad — it is that the GBM looks good for the
wrong reason. Three things could fake skill, and each gets a test that plants the
fault rather than asserting its absence:

  * the **target encoding** is a per-constraint binding rate, and computed over the
    whole panel it simply *is* the target;
  * the **climatology buckets** are quantile edges, which leak the scored week's
    distribution if fitted across it;
  * the **walk itself** must never let the scored week into the fit.

The fourth test is about honesty rather than leakage: head 1's headline metric is
calibration, and a model can rank perfectly (AUC 1.0) while being systematically
wrong about magnitude — which is exactly what would corrupt commit 5's bands.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.mu.mu_model import (FEATURE_SETS, PRIOR_STRENGTH, apply_encoding,
                                 arms_for, bind_metrics, feature_cols,
                                 fit_mu_climatology, load_preds, mu_head_verdict,
                                 predict_day, predict_mu_climatology,
                                 refit_boundaries, reliability, save_preds,
                                 target_encoding, walk_forward)


def _panel(n_days: int = 60, keys=("A|c", "B|c"), seed: int = 0) -> pd.DataFrame:
    """A panel with real structure: A binds when net load is high, B never binds."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range("2025-01-01", periods=n_days * 24, freq="h", tz="UTC")
    rows = []
    for h in hours:
        net = 40000 + 20000 * np.sin(h.hour / 24 * 2 * np.pi) + rng.normal(0, 2000)
        for k in keys:
            binds = int(k == "A|c" and net > 50000)
            rows.append({
                "interval_ts": h, "key": k,
                "net_load": net, "hour": h.hour, "dow": h.dayofweek,
                "binds_7d": 10.0 if k == "A|c" else 0.0,
                "y_bind": binds,
                "y_mu": (net - 50000) / 100 if binds else np.nan,
            })
    return pd.DataFrame(rows).set_index(["interval_ts", "key"]).sort_index()


# --------------------------------------------------- the ablation arms (0088)

def _armed_panel() -> pd.DataFrame:
    p = _panel(n_days=5)
    p["lag_mu_1d"] = 1.0
    p["geo_dist_wind_north"] = 2.0
    p["wx_corr_load_north"] = 3.0
    p["out_exposure_now"] = 4.0             # plan/0089 — the outage arm's prefix
    p["vintage_load"] = pd.Timestamp("2025-01-01", tz="UTC")
    return p


def test_base_arm_sees_no_arm_column():
    """`base` is 0085's feature set — the control the whole ablation is read
    against. If an arm column leaked into it, every arm would be measured against
    a moving baseline and the table would mean nothing."""
    cols = feature_cols(_armed_panel(), arms=())
    assert "net_load" in cols          # base features are always present
    assert not [c for c in cols if c.startswith(("lag_", "geo_", "wx_", "out_"))]


def test_each_arm_adds_only_its_own_columns():
    p = _armed_panel()
    base = set(feature_cols(p, arms=()))
    for arm, col in [("lag", "lag_mu_1d"), ("geo", "geo_dist_wind_north"),
                     ("wx", "wx_corr_load_north")]:
        got = set(feature_cols(p, arms=(arm,)))
        assert got - base == {col}, f"arm {arm!r} pulled in the wrong columns"


def test_all_arm_is_every_arm_and_the_targets_are_never_features():
    p = _armed_panel()
    cols = feature_cols(p, arms=arms_for("all"))
    assert {"lag_mu_1d", "geo_dist_wind_north", "wx_corr_load_north"} <= set(cols)
    # the bookkeeping columns stay out of every arm, `all` included
    assert not {"y_mu", "y_bind", "delivery_day", "vintage_load"} & set(cols)


def test_arms_are_nested_base_subset_of_single_subset_of_all():
    """The ablation is only readable if the arms are nested: `+lag` must be `base`
    plus lagged mu and NOTHING else. A non-nested arm makes a difference in the
    score unattributable to the covariate."""
    p = _armed_panel()
    base, all_ = set(feature_cols(p, arms=())), set(feature_cols(p, arms=arms_for("all")))
    for name in ("lag", "geo", "wx"):
        arm = set(feature_cols(p, arms=arms_for(name)))
        assert base < arm < all_


def test_unknown_feature_set_is_refused_rather_than_silently_scoring_base():
    """A typo'd `--features` must not quietly produce a `base` run labelled as an
    arm — that is a wrong number with a confident name on it."""
    with pytest.raises(ValueError, match="unknown feature set"):
        arms_for("lagg")
    with pytest.raises(ValueError, match="unknown arm"):
        feature_cols(_armed_panel(), arms=("outage",))


def test_every_feature_set_resolves():
    p = _armed_panel()
    for name in FEATURE_SETS:
        assert feature_cols(p, arms=arms_for(name))


def test_outage_arm_is_isolated_and_leaves_0088_arms_untouched():
    """plan/0089's arm is additive: `out` is `base` plus the outage exposure and
    NOTHING else, and — the load-bearing claim — introducing the `out_` prefix must
    leave 0088's frozen `base` and `all` byte-identical even on a panel that carries
    the covariate, so the two branches remain comparable week-for-week."""
    p = _armed_panel()
    base = set(feature_cols(p, arms=()))
    assert set(feature_cols(p, arms=arms_for("out"))) - base == {"out_exposure_now"}

    # base and all never see the outage column, however present it is in the panel.
    assert "out_exposure_now" not in base
    all_ = set(feature_cols(p, arms=arms_for("all")))
    assert "out_exposure_now" not in all_
    # all+out is exactly 0088's all plus the outage exposure.
    assert set(feature_cols(p, arms=arms_for("all+out"))) - all_ == {"out_exposure_now"}


# ------------------------------------------------------- the target encoding

def test_target_encoding_is_blind_to_the_scored_week():
    """THE leak test for head 1's identity feature.

    Constraint B never binds in training. Make it bind in EVERY hour of the scored
    week. Its encoded rate must not move — the encoding is fitted on train, and if
    it ever reflects the scored week, the model is reading its own target.
    """
    panel = _panel()
    ts = panel.index.get_level_values("interval_ts")
    split = ts[0] + pd.Timedelta(days=50)
    train, score = panel[ts < split], panel[ts >= split].copy()

    enc, pooled = target_encoding(train)
    before = apply_encoding(score, enc, pooled)["key_bind_rate"]

    score.loc[(slice(None), "B|c"), "y_bind"] = 1          # the whole week binds
    after = apply_encoding(score, enc, pooled)["key_bind_rate"]

    pd.testing.assert_series_equal(before, after)


def test_target_encoding_shrinks_a_thin_constraint_toward_the_pool():
    """A constraint seen for 3 hours must not be handed a 1.0 binding rate.

    This is what makes pooling work for the thin binders — and after 0084 killed
    `min_hours=25`, roughly half the map's columns ARE thin binders.
    """
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(hours=i), "thin")
         for i in range(3)]
        + [(pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(hours=i), "fat")
           for i in range(400)],
        names=["interval_ts", "key"])
    train = pd.DataFrame({"y_bind": [1, 1, 1] + [0] * 400}, index=idx)

    enc, pooled = target_encoding(train)
    raw_thin = 1.0
    assert enc["thin"] < raw_thin / 2          # pulled hard toward the pool
    assert enc["thin"] > pooled                # but still above a never-binder
    # The shrinkage is exactly the prior weight, not a magic number.
    assert enc["thin"] == pytest.approx((3 + PRIOR_STRENGTH * pooled)
                                        / (3 + PRIOR_STRENGTH))


def test_unseen_constraint_falls_back_to_the_pooled_rate():
    """A key the training window never saw gets the typical constraint's rate —
    not NaN (which the GBM would read as a category) and not 0 (a confident claim
    we have no basis for)."""
    panel = _panel()
    enc = pd.Series({"A|c": 0.4}, dtype="float32")
    out = apply_encoding(panel, enc, pooled=0.05)
    unseen = out.xs("B|c", level="key")["key_bind_rate"].to_numpy()
    assert np.allclose(unseen, 0.05)
    assert not np.isnan(unseen).any()


# ------------------------------------------------------- the climatology

def test_climatology_edges_come_only_from_the_training_window():
    """Quantile edges fitted across the scored week leak its distribution."""
    panel = _panel()
    ts = panel.index.get_level_values("interval_ts")
    split = ts[0] + pd.Timedelta(days=50)
    train = panel[ts < split]

    cells, edges, grand = fit_mu_climatology(train)
    score = panel[ts >= split].copy()
    base = predict_mu_climatology(score, cells, edges, grand)

    score["net_load"] = score["net_load"] * 10       # an absurd scored week
    shifted = predict_mu_climatology(score, cells, edges, grand)

    # Edges are frozen, so the shifted week piles into the top bucket rather than
    # redrawing the buckets around itself.
    assert not np.array_equal(base, shifted)
    assert np.isfinite(shifted).all()


def test_climatology_trains_on_binders_only():
    """`E[mu | bind]` — the unconditional mean is mostly zeros and is a different
    quantity entirely."""
    panel = _panel()
    cells, edges, grand = fit_mu_climatology(panel)
    binder_mean = panel.loc[panel["y_bind"] == 1, "y_mu"].mean()
    assert grand == pytest.approx(binder_mean)
    assert grand > 0


# ------------------------------------------------------- calibration

def test_bind_metrics_lead_with_calibration_not_auc():
    """A perfectly RANKED but badly CALIBRATED model.

    p is monotone in y, so AUC is 1.0 — flawless discrimination. But every
    probability is inflated ~3x. Commit 5 samples binding sets from these numbers,
    so this model would produce beautifully ordered and systematically wrong bands.
    AUC cannot see it; Brier and ECE must.
    """
    rng = np.random.default_rng(0)
    y = rng.binomial(1, 0.1, 4000)
    p = np.where(y == 1, 0.9, 0.3)          # perfect ranking, 3x over-confident

    m = bind_metrics(y, p)
    assert m["auc"] == pytest.approx(1.0)   # AUC says "perfect"
    assert m["ece"] > 0.2                   # calibration says otherwise
    assert m["mean_pred"] > 2 * m["base_rate"]


def test_reliability_curve_locates_the_miscalibration():
    y = np.array([0] * 90 + [1] * 10)
    p = np.array([0.5] * 100)               # says 50%, happens 10% of the time
    rel = reliability(y, p, n_bins=10)
    row = rel.loc[rel["n"] > 0].iloc[0]
    assert row["gap"] == pytest.approx(-0.4)   # over-confident by 40 points


# ------------------------------------------------------- the walk

def test_walk_forward_never_trains_on_the_scored_week():
    """The end-to-end leak test: poison a scored week, check THAT fold.

    Set y_bind=1 and a huge y_mu across the first scored week. That fold's models
    were fitted on the window ENDING at its start, so its predictions must be
    bit-identical. If the fit reached forward even by one hour, they move.

    Only the first fold is compared, and the reason is worth stating because the
    naive version of this test fails for an innocent reason: as the window rolls,
    week 1's scored rows legitimately BECOME week 2's training rows. Later folds
    are therefore *supposed* to react to the poison. Asserting they don't would be
    asserting the walk doesn't walk.
    """
    panel = _panel(n_days=40)
    preds, _ = walk_forward(panel, train_days=21, refit_days=7)
    assert not preds.empty

    first = preds["week"].min()
    fold = preds[preds["week"] == first]
    scored_hours = fold.index.get_level_values("interval_ts").unique()

    poisoned = panel.copy()
    hit = poisoned.index.get_level_values("interval_ts").isin(scored_hours)
    poisoned.loc[hit, "y_bind"] = 1
    poisoned.loc[hit, "y_mu"] = 5000.0

    preds2, _ = walk_forward(poisoned, train_days=21, refit_days=7)
    fold2 = preds2[preds2["week"] == first]

    # The realized targets differ (we poisoned them) — the PREDICTIONS must not.
    for col in ("p_bind", "mu_clim", "mu_gbm"):
        np.testing.assert_allclose(fold[col].to_numpy(), fold2[col].to_numpy())
    # And the poison really was applied, or the test proves nothing.
    assert fold2["y_bind"].all() and not fold["y_bind"].all()


def test_refit_grid_matches_the_sf_eval_convention():
    """Anchored at origin + train_days, stepping by refit_days."""
    panel = _panel(n_days=60)
    starts = refit_boundaries(panel, train_days=30, refit_days=7)
    assert starts[0] == pd.Timestamp("2025-01-31", tz="UTC")
    assert (starts.to_series().diff().dropna() == pd.Timedelta(days=7)).all()


def test_score_from_is_a_grid_point_not_just_a_filter():
    """The alignment bug, pinned from the only side that ever mattered.

    Commit 4 scores every mu source on IDENTICAL weeks, and commit 5 pushes them
    through an SF map refit on `sf/eval`'s grid — so the phase has to match, not
    merely the 7-day cadence.

    This drifted twice, silently, because a misphased run still produces 46 tidy
    weeks: anchored on the covariate panel the weeks began 2025-08-16 against sf's
    2025-08-14; anchored on this run's shadow-price panel, 2025-08-15. Deriving the
    phase is the bug. `score_from` is handed a real sf week, so the grid must START
    there — exactly, not at the next inferred boundary at or after it.
    """
    panel = _panel(n_days=400)                       # starts 2025-01-01
    sf_week = pd.Timestamp("2025-08-14", tz="UTC")   # a real sf/eval score_start

    starts = refit_boundaries(panel, train_days=30, refit_days=7, score_from=sf_week)

    assert starts[0] == sf_week                      # the exact week, not "on or after"
    assert (starts.to_series().diff().dropna() == pd.Timedelta(days=7)).all()

    # An inferred phase would have to be lucky to land here. Prove it does not:
    # the panel's own anchor puts the grid a day off, which is precisely the drift.
    inferred = refit_boundaries(panel, train_days=30, refit_days=7)
    assert sf_week not in inferred


def test_short_first_window_is_refused_not_silently_scored():
    """A scored week whose training window runs off the front of the panel would
    train on less history than every other week and be reported beside them as an
    equal. Refuse it loudly instead."""
    panel = _panel(n_days=400)                       # starts 2025-01-01
    with pytest.raises(ValueError, match="refusing"):
        refit_boundaries(panel, train_days=240, refit_days=7,
                         score_from=pd.Timestamp("2025-02-01", tz="UTC"))


def test_walk_forward_learns_the_planted_structure():
    """Sanity: A binds iff net load is high, so a working head 1 must separate.

    Without this, the leak tests above could all pass on a model that has learned
    nothing at all.
    """
    panel = _panel(n_days=60)
    preds, weekly = walk_forward(panel, train_days=30, refit_days=7)
    assert weekly["auc"].mean() > 0.9
    assert preds.loc[preds["y_bind"] == 1, "p_bind"].mean() > \
           preds.loc[preds["y_bind"] == 0, "p_bind"].mean()


def test_preds_round_trip_through_npz(tmp_path):
    """Everything commits 4 and 5 score is read back from this file.

    Three things a naive save would lose, each of which corrupts a downstream
    number rather than raising: the tz-aware timestamps (npz has no tz dtype, and
    a silent shift to naive re-introduces exactly the hour-error the leak audit
    exists to catch), the NaN in `y_mu` that MEANS "did not bind", and the key
    strings behind the factorized codes.
    """
    panel = _panel(n_days=40)
    preds, _ = walk_forward(panel, train_days=21, refit_days=7)
    assert preds["y_mu"].isna().any(), "fixture must contain non-binding rows"

    path = str(tmp_path / "preds.npz")
    save_preds(path, preds)
    back = load_preds(path)

    assert back.index.get_level_values("interval_ts").tz is not None
    pd.testing.assert_index_equal(back.index, preds.index)
    np.testing.assert_allclose(back["p_bind"], preds["p_bind"].astype("float32"))
    # NaN survives as NaN — not as 0, which would read as "bound at $0".
    pd.testing.assert_series_equal(back["y_mu"].isna(), preds["y_mu"].isna(),
                                   check_names=False)
    assert (back["week"] == preds["week"]).all()


def test_mu_head_verdict_defaults_to_climatology_on_a_tie():
    """The plan pre-registered climatology as the backbone; the GBM must EARN it."""
    tie = pd.DataFrame({"mae_mu_clim": [10.0, 10.0], "mae_mu_gbm": [10.0, 10.0]})
    assert mu_head_verdict(tie).startswith("climatology")


# --------------------------------------------- forward inference (0012, stage 1)

def test_predict_day_reconciles_with_walk_forward():
    """The decisive stage-1 test: forward inference must equal walk-forward on a day
    both can see. `predict_day` is one `walk_forward` fold with the prediction block
    narrowed to D's 24 h — so for a historic D that IS a refit-grid start, the same
    trailing window fits the same heads, and the served predictions for D must be
    bit-identical. If they drift, the extracted fold and the walk have diverged (the
    single failure this branch exists to prevent).
    """
    panel = _panel(n_days=60)
    D = refit_boundaries(panel, train_days=30, refit_days=7)[0]
    preds, _ = walk_forward(panel, train_days=30, refit_days=7)

    wp = predict_day(panel, D, train_days=30)

    # The forecast granularity is the hour: 24 tz-aware hourly rows per scored key.
    assert wp["interval_ts"].nunique() == 24
    assert wp["interval_ts"].dt.tz is not None

    wf = preds.reset_index()
    day = wf[(wf["interval_ts"] >= D) & (wf["interval_ts"] < D + pd.Timedelta(days=1))]
    assert set(wp["key"]).issubset(set(day["key"]))
    for k in wp["key"].unique():
        a = wp[wp["key"] == k].set_index("interval_ts").sort_index()
        b = day[day["key"] == k].set_index("interval_ts").sort_index()
        np.testing.assert_allclose(a["p_bind"].to_numpy(), b["p_bind"].to_numpy())
        np.testing.assert_allclose(a["mu_gbm"].to_numpy(), b["mu_gbm"].to_numpy())


def test_predict_day_drops_historyless_key_and_counts_novelty():
    """A constraint with no binding history gets no row, and is counted — not
    silently zeroed. In the fixture B binds never but is enforced (present) every
    day, so it is the coverage gap: absent from the scored `wp`, surfaced as novelty.
    """
    panel = _panel(n_days=60)
    D = refit_boundaries(panel, train_days=30, refit_days=7)[0]

    wp = predict_day(panel, D, train_days=30)

    assert "A|c" in set(wp["key"])            # has binding history → scored
    assert "B|c" not in set(wp["key"])        # no binding history → no row
    assert wp.attrs["novelty"] == 1
    assert wp.attrs["novel_keys"] == ["B|c"]
