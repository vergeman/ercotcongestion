"""The two heads: P(bind) and E[mu | bind].

plan/0085 commit 3.

**Pooled, not per-constraint.** One model over all constraints, with constraint
identity entering as *features* (its own binding history, plus a target-encoded
binding rate) rather than as N separate models. A per-constraint GBM for something
that binds 5 hours in 240 days is hopeless, and 0084's guard sweep has now made
that the common case rather than the exception: `min_hours=25` is dead, so the map
carries ~1,650-2,200 columns and roughly half of them are thin binders. Pooling
borrows strength across constraints and is robust to either operating point.

**Head 1 — P(bind at h).** Gradient-boosted classifier. The headline metric is
**calibration**, not AUC, and the distinction is not pedantry: commit 5 samples
binding sets from these probabilities and pushes them through the SF map to get
nodal P10/P50/P90. A model that ranks perfectly but says 0.9 when it means 0.5
produces beautifully ordered, systematically wrong bands. AUC cannot see that;
Brier and the reliability curve can.

**Head 2 — E[mu | bind].** The plan says conditional climatology FIRST, quantile
regression only if the simple version is beaten — so both are built and scored
head-to-head here, and `mu_head` reports which won rather than assuming. The
climatology is bucketed on net load, which is the physical driver: congestion
magnitude is a function of how hard the system is being pushed.

**Honest walk-forward.** Train on the trailing window ending STRICTLY BEFORE the
scored week — the same convention as `sf/eval.evaluate`, whose refit grid this
deliberately mirrors so the two can be compared week-for-week in commit 4. Every
quantity fitted on training data (including the target encoding and the
climatology buckets) is fitted inside the window and applied forward. There are no
exceptions and no "just for the sweep".
"""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import (HistGradientBoostingClassifier,
                              HistGradientBoostingRegressor)
from sklearn.metrics import brier_score_loss, roc_auc_score

from compute.mu.features import BIND_DEADBAND

log = logging.getLogger("compute.mu.mu_model")

# Mirrors the SF operating point adopted in 0082 (window=240d, refit=7d) so the
# mu-model's scored weeks land on the same boundaries as the SF map's.
DEFAULT_TRAIN_DAYS = 240
DEFAULT_REFIT_DAYS = 7

# Columns that are targets or bookkeeping, never inputs.
NON_FEATURES = ("y_mu", "y_bind", "delivery_day")

# Smoothing for the target encoding. A constraint seen for 3 hours should not be
# handed a 1.0 binding rate; it should be pulled most of the way back to the pooled
# mean. `n / (n + PRIOR_STRENGTH)` is the weight its own history gets.
PRIOR_STRENGTH = 50.0

MU_FLOOR = 1.0   # $/MWh; log1p is taken on mu, so this only guards the tail

# The on-disk bind matrix (see `_alloc_bind_matrix`). One fixed file, reused every
# fold, so at most one ~3.4 GB matrix is ever on the PVC; the walk unlinks it.
_BIND_MATRIX_FILE = "bind_matrix.f64"

# The on-disk Arrow copy of the panel's feature block (see `spill_panel_features`),
# opt-in via MU_SPILL_PANEL. One file, overwritten per run, unlinked when main ends.
_PANEL_FILE = "panel_features.arrow"


# --------------------------------------------------------------------------
# The ablation arms (plan/0088)
# --------------------------------------------------------------------------
# **Build the panel once; express an arm as a subset of its columns.** This is
# the load-bearing engineering decision of 0088 and it is worth being explicit
# about why: `build_panel` materialises ~10M rows and is the peak-memory line of
# the package. Rebuilding it five times to run five arms would cost five walks'
# worth of the most expensive step in the branch — and, far worse, would leave
# five *separately constructed* panels whose differences are not guaranteed to be
# only the arm. Here the panel is a fixed object and the arm is a column mask, so
# "the only thing that varies is the feature set" is a fact about the code rather
# than a claim in a docstring.
#
# Each arm owns a column-name prefix. A new covariate joins an arm by being named
# for it; there is no registry to update and no way for a column to be silently
# claimed by the wrong arm.
ARM_PREFIXES = {
    "lag": "lag_",   # commit 2 — lagged realized mu (the persistence content)
    "geo": "geo_",   # commit 3 — constraint geography via the |SF| centroid
    "wx": "wx_",     # commit 4 — per-constraint weather-response vectors
    "out": "out_",   # plan/0089 — per-constraint generation-outage exposure
}

# `base` is 0085's feature set exactly — the thing every arm must be measured
# against. `all` is every arm at once. The single-arm rows are what make the
# contributions attributable.
#
# **The first five keys are 0088's pre-registered arms (`plan/s6-gate.md`) and are
# frozen — do not edit them.** `out` and `all+out` are plan/0089's additions, and
# they are additive on purpose: because `out` joins `ARM_PREFIXES`, every existing
# arm now *drops* the `out_` columns, so `base` and `all` are byte-identical to 0088
# on a panel that carries the outage covariate. The new arms are the only ones that
# can see it.
FEATURE_SETS = {
    "base": (),
    "lag": ("lag",),
    "geo": ("geo",),
    "wx": ("wx",),
    "all": ("lag", "geo", "wx"),
    "out": ("out",),                        # plan/0089 — outage exposure alone
    "all+out": ("lag", "geo", "wx", "out"),  # plan/0089 — 0088's `all` + outage
}


def feature_cols(panel: pd.DataFrame, arms: tuple[str, ...] = ("lag", "geo", "wx"),
                 ) -> list[str]:
    """The feature columns for one arm.

    A column belongs to an arm iff it carries that arm's prefix; everything else
    is `base`. Selecting an arm therefore means *dropping* the prefixed columns of
    the arms not selected — the base features are always present, in every arm.

    The default is every arm, so a caller that does not care about the ablation
    (the tests, any downstream user) keeps the old behaviour of "all the columns
    there are".
    """
    unknown = set(arms) - set(ARM_PREFIXES)
    if unknown:
        raise ValueError(f"unknown arm(s): {sorted(unknown)}; "
                         f"known: {sorted(ARM_PREFIXES)}")

    dropped = tuple(p for a, p in ARM_PREFIXES.items() if a not in arms)
    return [c for c in panel.columns
            if c not in NON_FEATURES
            and not c.startswith("vintage_")
            and not c.startswith(dropped)]


def arms_for(features: str) -> tuple[str, ...]:
    """Resolve a `--features` name to its arms. Refuses an unknown name rather
    than silently scoring `base` and calling it something else."""
    if features not in FEATURE_SETS:
        raise ValueError(f"unknown feature set {features!r}; "
                         f"known: {sorted(FEATURE_SETS)}")
    return FEATURE_SETS[features]


# --------------------------------------------------------------------------
# Constraint identity, without a per-constraint model
# --------------------------------------------------------------------------

def target_encoding(train: pd.DataFrame) -> tuple[pd.Series, float]:
    """Smoothed binding rate per constraint, fitted on TRAIN ONLY.

    This is the feature that carries constraint identity into a pooled model. It
    is also the single most dangerous feature in the package: computed over the
    whole panel it would encode the scored week's own binding rate, which is the
    target. It is therefore fitted here, from `train`, and applied forward — and
    `test_target_encoding_is_blind_to_the_scored_week` pins that.

    Returns `(per-key rate, pooled mean)`. The pooled mean is the fallback for a
    key the training window never saw — the honest answer for a constraint we know
    nothing about is "whatever a typical constraint does".
    """
    g = train.groupby(level="key")["y_bind"]
    n, k = g.count(), g.sum()
    pooled = float(train["y_bind"].mean()) if len(train) else 0.0
    smoothed = (k + PRIOR_STRENGTH * pooled) / (n + PRIOR_STRENGTH)
    return smoothed.astype("float32"), pooled


def apply_encoding(panel: pd.DataFrame, enc: pd.Series, pooled: float,
                   columns: list[str] | None = None) -> pd.DataFrame:
    """Attach the target-encoded `key_bind_rate`, on a copy of the fold.

    `columns` slims that copy to the columns the walk will actually read. The
    ablation panel carries **every** arm's columns (~90), but a single arm's fold
    consumes only its own features plus the two targets (~50) — copying all 90 per
    fold was a ~2x-wider allocation than the walk uses, and per-fold copies are the
    peak-memory line of the walk. Under copy-on-write `panel[columns]` shares data
    until `.copy()`, so this stays a single slim materialisation rather than two.
    `columns=None` keeps the old whole-fold behaviour for callers that want it.
    """
    src = panel if columns is None else panel[columns]
    out = src.copy()
    keys = out.index.get_level_values("key")
    out["key_bind_rate"] = enc.reindex(keys).fillna(pooled).to_numpy("float32")
    return out


# --------------------------------------------------------------------------
# Head 1 — P(bind)
# --------------------------------------------------------------------------

def fold_matrix(frame: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """A feature matrix as float64, built column by column into a pre-allocated
    F-order array. HistGBM upcasts X to float64 for binning regardless of input
    dtype — there is no float32 path — so handing it the float64 directly changes no
    value. Used for the scored week (small); the train-side bind matrix is filled
    inline in `walk_forward` straight from the panel view to skip the wide float32
    fold copy the wide `all` arm cannot afford. F-order matches HistGBM's binning.
    """
    x = np.empty((len(frame), len(cols)), dtype=np.float64, order="F")
    for j, c in enumerate(cols):
        x[:, j] = frame[c].to_numpy()
    return x


def _alloc_bind_matrix(shape: tuple[int, int], spill_dir: str | None) -> np.ndarray:
    """The fold's float64 bind matrix — on the disk PVC when `spill_dir` is given.

    This is the single largest live allocation in the walk: `n_train × (n_feat+1)`
    float64, ~3.4 GB on the wide `all` arm late in the walk, and it MUST coexist
    with the ~4.3 GB resident panel while `fit_bind_head` bins it. As two anonymous
    allocations that is ~8 GB the node can only reclaim by OOM-killing the process —
    the observed "~10 GB then exit 137".

    Backed by a flushed `np.memmap` on the disk PVC instead, the matrix is *clean
    file-backed page cache*: under memory pressure the node evicts it rather than
    killing the fit, so the walk's anonymous working set drops by the full matrix.
    The caller fills every cell, so values are bit-identical to `np.empty` and
    `compare_base`/determinism are unaffected. F-order matches HistGBM's binning.

    `spill_dir=None` keeps the in-RAM allocation — the path tests and the small
    daily `predict_day` fold take, where the matrix is not worth a disk round-trip.
    """
    if spill_dir is None:
        return np.empty(shape, dtype=np.float64, order="F")
    os.makedirs(spill_dir, exist_ok=True)
    return np.memmap(os.path.join(spill_dir, _BIND_MATRIX_FILE),
                     dtype=np.float64, mode="w+", shape=shape, order="F")


def fit_bind_head(x: np.ndarray, y: np.ndarray,
                  seed: int = 0) -> HistGradientBoostingClassifier:
    """Gradient-boosted classifier. NaN goes in natively — see `build_panel`'s note
    on why the covariate holes must not be filled. `x` is the fold's float64 feature
    matrix from `fold_matrix`, built by the caller so the float32 fold copy is freed
    before this fit; positional columns, so the caller keeps `cols` order stable."""
    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.06, max_leaf_nodes=31,
        min_samples_leaf=100, l2_regularization=1.0,
        early_stopping=False, random_state=seed)
    model.fit(x, y)
    return model


def reliability(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """The reliability curve: in the bucket where we said ~x, how often did it happen?

    Reported alongside Brier because Brier is a single number that mixes
    calibration and resolution; the curve says *where* the model lies, which is
    what tells you whether the downstream bands are trustworthy at the high-p end
    (the only end anyone acts on).
    """
    edges = np.linspace(0, 1, n_bins + 1)
    b = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    df = pd.DataFrame({"bin": b, "p": p, "y": y})
    out = df.groupby("bin").agg(n=("y", "size"), p_mean=("p", "mean"),
                                y_rate=("y", "mean"))
    out["gap"] = out["y_rate"] - out["p_mean"]
    return out


def bind_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    """Calibration first, discrimination second — deliberately in that order."""
    rel = reliability(y, p)
    # Weight each bin's miscalibration by how much of the mass sits in it.
    ece = float((rel["n"] / rel["n"].sum() * rel["gap"].abs()).sum())
    return {
        "brier": float(brier_score_loss(y, p)),
        "ece": ece,
        "auc": float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else np.nan,
        "base_rate": float(y.mean()),
        "mean_pred": float(p.mean()),
    }


# --------------------------------------------------------------------------
# Head 2 — E[mu | bind]
# --------------------------------------------------------------------------

def fit_mu_climatology(train: pd.DataFrame, n_buckets: int = 6
                       ) -> tuple[pd.Series, np.ndarray, float]:
    """Conditional climatology: mean mu per (net-load bucket x hour-of-day), on binders.

    The plan's stated backbone, and the thing quantile regression has to beat.
    Bucket edges come from the TRAINING window's net load only — fitting them
    across train+test would leak the scored week's distribution (the same mistake
    `legacy/regimes/binners._qcut` makes).
    """
    binders = train[train["y_bind"] == 1]
    grand = float(binders["y_mu"].mean()) if len(binders) else 0.0
    if binders.empty:
        return pd.Series(dtype="float64"), np.array([]), grand

    edges = np.unique(np.quantile(train["net_load"].dropna(),
                                  np.linspace(0, 1, n_buckets + 1)[1:-1]))
    cells = binders.groupby([np.digitize(binders["net_load"], edges),
                             binders["hour"]])["y_mu"].mean()
    return cells, edges, grand


def predict_mu_climatology(panel: pd.DataFrame, cells: pd.Series,
                           edges: np.ndarray, grand: float) -> np.ndarray:
    if cells.empty:
        return np.full(len(panel), grand)
    idx = pd.MultiIndex.from_arrays([np.digitize(panel["net_load"], edges),
                                     panel["hour"]])
    return cells.reindex(idx).fillna(grand).to_numpy()


def fit_mu_head(train: pd.DataFrame, cols: list[str],
                seed: int = 0) -> HistGradientBoostingRegressor:
    """GBM on log1p(mu), trained on BINDING rows only.

    Two choices worth stating. Training only on binders is what makes this
    `E[mu | bind]` rather than `E[mu]` — the unconditional mean is mostly zeros
    and would be a different (and useless) quantity. And mu is heavy-tailed
    (measured max $1,088 against a mean of $48), so a squared-error fit on the raw
    scale would spend the model on a handful of extreme hours; log1p pulls that in
    and the prediction is mapped back with expm1.
    """
    binders = train[train["y_bind"] == 1]
    model = HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.06, max_leaf_nodes=31,
        min_samples_leaf=50, l2_regularization=1.0,
        early_stopping=False, random_state=seed)
    model.fit(binders[cols], np.log1p(binders["y_mu"].clip(lower=MU_FLOOR)))
    return model


def predict_mu_head(model: HistGradientBoostingRegressor, panel: pd.DataFrame,
                    cols: list[str]) -> np.ndarray:
    return np.expm1(model.predict(panel[cols])).clip(min=0.0)


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------

def refit_boundaries(panel: pd.DataFrame, train_days: int, refit_days: int,
                     score_from: pd.Timestamp | None = None,
                     anchor: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    """The weekly refit grid, phase-locked to `sf/eval`.

    **`score_from` IS a grid point, and that is the whole trick.** Commit 4 scores
    every mu source in one harness on IDENTICAL weeks, and commit 5 pushes those
    weeks through an SF map refit on `sf/eval`'s grid — so a grid that is merely
    *weekly* is not enough, it has to be weekly **in the same phase**.

    `sf/eval` derives its phase from `days[0] + train_days` of whatever panel that
    run loaded. Reproducing that here means reproducing a start date we do not
    otherwise need, and getting it wrong is silent: the run still produces 46
    tidy weeks, just not the same 46. It has now been wrong twice — anchored on
    the covariate panel the weeks landed 2 days late, and anchored on this run's
    shadow-price panel (which starts at the covariate range, not the SF sweep's)
    still 1 day late, at 2025-08-15 against sf's 2025-08-14.

    So stop deriving the phase and take it. `--score-from` is already given a real
    `sf/eval` week start, which pins the phase exactly with nothing left to infer.
    `anchor` remains only for the no-`score_from` case (tests, standalone use),
    where there is no week to lock onto.
    """
    days = pd.DatetimeIndex(
        panel.index.get_level_values("interval_ts").normalize().unique()).sort_values()

    if score_from is not None:
        origin = pd.Timestamp(score_from).tz_convert(days.tz)
        if origin - pd.Timedelta(days=train_days) < days[0]:
            raise ValueError(
                f"score_from={origin.date()} needs {train_days}d of history back to "
                f"{(origin - pd.Timedelta(days=train_days)).date()}, but the panel "
                f"starts {days[0].date()}. The first week would train on a short "
                f"window and score anyway — refusing.")
        return pd.date_range(origin, days[-1], freq=pd.Timedelta(days=refit_days),
                             inclusive="left")

    origin = pd.Timestamp(anchor).tz_convert(days.tz) if anchor is not None else days[0]
    return pd.date_range(origin + pd.Timedelta(days=train_days), days[-1],
                         freq=pd.Timedelta(days=refit_days), inclusive="left")


def _predict_fold(train: pd.DataFrame, score: pd.DataFrame,
                  arms: tuple[str, ...] = ("lag", "geo", "wx"),
                  seed: int = 0, spill_dir: str | None = None) -> pd.DataFrame:
    """One fold: fit both heads on `train`, predict `score`. Predictions only.

    `spill_dir`, when given, puts the float64 bind matrix on that disk PVC instead
    of anonymous RAM (see `_alloc_bind_matrix`) — the walk's peak-memory line.

    This is the body `walk_forward`'s loop used to inline, lifted out verbatim so
    the production forward path (`predict_day`) and the validated backtest fit are
    literally the same code — a re-fit that drifts from the walk is the failure the
    extraction exists to prevent. Returns one row per scored `(interval_ts, key)`
    with `p_bind`, `mu_clim`, `mu_gbm`, indexed by `score`'s index. The realized
    `y_bind`/`y_mu` join stays with the caller that holds the labels.

    `keep` slims the per-fold copy to this arm's features plus the two targets: the
    ablation panel carries ~90 columns, but a single arm's fold reads only ~50, and
    per-fold copies are the peak-memory line of the walk — see `apply_encoding`.
    """
    feat = feature_cols(train, arms)
    cols = feat + ["key_bind_rate"]
    keep = feat + ["y_bind", "y_mu"]

    enc, pooled = target_encoding(train)
    score_e = apply_encoding(score, enc, pooled, keep)

    # Never materialise the full-width float32 fold copy. On the wide `all` arm
    # (86 features) that copy is ~1.7 GB and it has to coexist with the ~3.3 GB
    # float64 bind matrix while the matrix is filled — together, on top of the
    # ~4 GB panel, that tips the densest late-walk folds over this node's RAM.
    # `apply_encoding` only *adds* one column (`key_bind_rate`); every other fold
    # column is a raw panel column already in `train`. So the bind matrix is filled
    # straight from the panel view plus that one encoded column, and only the small
    # consumers are encoded in full: the mu head trains on binding rows alone (a few
    # percent), and the climatology reads four base columns off the view. Each value
    # is exactly what a full `apply_encoding` then `fold_matrix` produced — same
    # float32 columns, same float32 `key_bind_rate` upcast to float64, same `cols`
    # order — so every fitted value is unchanged; `test`/`compare_base` pin it.
    binders_e = apply_encoding(train[train["y_bind"] == 1], enc, pooled, keep)
    clim_e = train[["net_load", "hour", "y_mu", "y_bind"]].copy()
    y_bind_tr = train["y_bind"].to_numpy()

    key_rate = enc.reindex(
        train.index.get_level_values("key")).fillna(pooled).to_numpy("float32")
    x_tr = _alloc_bind_matrix((len(train), len(cols)), spill_dir)
    for j, c in enumerate(feat):
        x_tr[:, j] = train[c].to_numpy()
    x_tr[:, len(feat)] = key_rate  # last column of `cols`; float32 → float64
    if isinstance(x_tr, np.memmap):
        x_tr.flush()  # msync the just-written 3.4 GB: dirty pages count as
                      # unreclaimable against the node/cgroup, clean ones it can
                      # evict — the flush is what averts the OOM, not the move alone.

    bind = fit_bind_head(x_tr, y_bind_tr, seed)
    del x_tr, y_bind_tr, key_rate
    p = bind.predict_proba(fold_matrix(score_e, cols))[:, 1]

    cells, edges, grand = fit_mu_climatology(clim_e)
    mu_clim = predict_mu_climatology(score_e, cells, edges, grand)
    mu_gbm = predict_mu_head(fit_mu_head(binders_e, cols, seed), score_e, cols)

    return pd.DataFrame(
        {"p_bind": p, "mu_clim": mu_clim, "mu_gbm": mu_gbm}, index=score_e.index)


def walk_forward(panel: pd.DataFrame,
                 train_days: int = DEFAULT_TRAIN_DAYS,
                 refit_days: int = DEFAULT_REFIT_DAYS,
                 score_from: pd.Timestamp | None = None,
                 anchor: pd.Timestamp | None = None,
                 seed: int = 0,
                 arms: tuple[str, ...] = ("lag", "geo", "wx"),
                 spill_dir: str | None = None,
                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit both heads on each trailing window; predict the next `refit_days`.

    `arms` selects the ablation arm (plan/0088): the panel is the same object in
    every arm, and only the column mask changes.

    Returns `(predictions, weekly)`:

      predictions  one row per scored (hour, constraint), with `p_bind`,
                   `mu_clim`, `mu_gbm` and the realized `y_bind` / `y_mu`. This is
                   what commit 4's harness and commit 5's sampler consume.
      weekly       one row per scored week: head-1 calibration and head-2 error,
                   so a bad week is visible as a week rather than averaged away.
    """
    feat = feature_cols(panel, arms)
    cols = feat + ["key_bind_rate"]
    ts = panel.index.get_level_values("interval_ts")
    starts = refit_boundaries(panel, train_days, refit_days, score_from, anchor)
    if not len(starts):
        return pd.DataFrame(), pd.DataFrame()

    # The panel is built hour by hour, so it arrives sorted by time — which lets a
    # fold be a contiguous `iloc` slice (a view) instead of `panel[(ts>=lo)&(ts<s)]`
    # (a fresh ~1 GB copy of 4.5M rows, twice per week, on top of the 2.5 GB panel).
    # Sortedness is what makes that legal, so check it rather than assume it.
    if not ts.is_monotonic_increasing:
        raise ValueError("panel must be sorted by interval_ts")

    log.info("walk_forward: train=%dd refit=%dd arms=%s — %d cols, %d weeks [%s → %s]",
             train_days, refit_days, ",".join(arms) or "base", len(cols),
             len(starts), starts[0].date(), starts[-1].date())

    preds, weeks = [], []
    t_walk = time.perf_counter()
    for i, s in enumerate(starts):
        t0 = time.perf_counter()
        lo = s - pd.Timedelta(days=train_days)
        hi = s + pd.Timedelta(days=refit_days)

        # STRICTLY before: the train slice ENDS at `s`, so the scored week never
        # touches the fit. `searchsorted(..., "left")` on `s` puts the first row of
        # the scored week at the boundary and excludes it from train — same
        # half-open window as the mask it replaces.
        # `ts.searchsorted`, not `np.searchsorted(np.asarray(ts), ...)`: pandas 3
        # renders a tz-aware index as an OBJECT array of Timestamps, which then
        # compares tz-aware against tz-naive datetime64 and raises. The index's own
        # searchsorted keeps both the timezone and the (microsecond) unit.
        a, b, c = ts.searchsorted([lo, s, hi], side="left")
        train, score = panel.iloc[a:b], panel.iloc[b:c]
        if train.empty or score.empty or train["y_bind"].sum() < 10:
            continue

        out = _predict_fold(train, score, arms, seed, spill_dir)
        # The realized targets stay here — `walk_forward` is the caller that holds
        # the labels; the fold routine produced predictions only.
        out["y_bind"] = score["y_bind"].to_numpy()
        out["y_mu"] = score["y_mu"].to_numpy()
        out["week"] = s
        preds.append(out)

        row = {"week": s, "n_train": len(train), "n_score": len(score),
               **bind_metrics(out["y_bind"].to_numpy(), out["p_bind"].to_numpy())}
        hit = out[out["y_bind"] == 1]
        if len(hit):
            for name in ("mu_clim", "mu_gbm"):
                err = hit[name] - hit["y_mu"]
                row[f"mae_{name}"] = float(err.abs().mean())
                ss = float(((hit["y_mu"] - hit["y_mu"].mean()) ** 2).sum())
                row[f"r2_{name}"] = (1.0 - float((err ** 2).sum()) / ss
                                     if ss > 0 else np.nan)
        weeks.append(row)

        # Per week, not every 8th: a 46-week walk is the long pole in this branch
        # and "is it stuck or is it slow" should not need a guess. The running ETA
        # is what makes an early kill (a misphased grid, a bad panel) cheap.
        dt = time.perf_counter() - t0
        done, elapsed = i + 1, time.perf_counter() - t_walk
        log.info("  week %2d/%d %s  %.0fs  (train %s, score %s)  eta %.0fm",
                 done, len(starts), s.date(), dt, f"{len(train):,}", f"{len(score):,}",
                 (elapsed / done) * (len(starts) - done) / 60)

    # The walk is done reading the on-disk bind matrix; drop it so the PVC is not
    # left holding a stale ~3.4 GB file between runs.
    if spill_dir is not None:
        try:
            os.remove(os.path.join(spill_dir, _BIND_MATRIX_FILE))
        except OSError:
            pass

    return (pd.concat(preds) if preds else pd.DataFrame(),
            pd.DataFrame(weeks))


# --------------------------------------------------------------------------
# Forward inference — one fold, prediction block = a single delivery day
# --------------------------------------------------------------------------

def predict_day(panel: pd.DataFrame, D: pd.Timestamp,
                *, train_days: int = DEFAULT_TRAIN_DAYS,
                arms: tuple[str, ...] = ("lag", "geo", "wx"),
                seed: int = 0) -> pd.DataFrame:
    """Fit both heads on the trailing window and predict delivery day `D`.

    This is `walk_forward`'s fold (`_predict_fold`) with the prediction block set to
    D's 24 hours — the same fit path the backtest validated, run forward one day.
    `train` = `[D − train_days, D)`, `score` = the 24 hours of `[D, D+1d)`. The
    panel is handed in already built at the DAM-close vintage (0013 builds it); this
    function reads no live inputs and holds no cutoff logic.

    **Candidate universe = keys present in the trailing window's binding history.**
    A constraint the fit never saw bind has no target-encoded identity and no μ-head
    signal, so it gets no row rather than a silently-zero one — the coverage gap is
    reported (the novelty count below), not buried. The fit itself uses the *full*
    train (every key's target encoding, every binder), exactly as `walk_forward`
    does; only the scored rows are narrowed to the universe.

    **Novelty** is surfaced, not fatal: the number of keys *enforced* on D−1 (present
    in the panel that day, whether or not they bound) that the fit universe never
    saw bind — a constraint active right now with no history to learn from. It rides
    on the result as `wp.attrs["novelty"]` / `wp.attrs["novel_keys"]` and is logged,
    for 0013's run summary to widen bands or flag rather than silently zero them.

    Returns `wp` = the flat `(interval_ts, key, p_bind, mu_gbm)` frame
    `propagate_window` consumes — `mu_clim` and the realized labels are dropped from
    the served shape (propagation reads `p_bind` and `mu_gbm` only).
    """
    ts = panel.index.get_level_values("interval_ts")
    if not ts.is_monotonic_increasing:
        raise ValueError("panel must be sorted by interval_ts")
    D = pd.Timestamp(D)
    D = D.tz_localize(ts.tz) if D.tz is None else D.tz_convert(ts.tz)
    D = D.normalize()

    def _empty(novel_keys: list[str]) -> pd.DataFrame:
        out = pd.DataFrame(columns=["interval_ts", "key", "p_bind", "mu_gbm"])
        out.attrs["novelty"] = len(novel_keys)
        out.attrs["novel_keys"] = novel_keys
        return out

    lo, hi = D - pd.Timedelta(days=train_days), D + pd.Timedelta(days=1)
    p_lo, p_dm1, p_d, p_hi = ts.searchsorted(
        [lo, D - pd.Timedelta(days=1), D, hi], side="left")
    train, score = panel.iloc[p_lo:p_d], panel.iloc[p_d:p_hi]
    if train.empty or score.empty:
        return _empty([])

    universe = pd.Index(
        train.index[train["y_bind"] == 1].get_level_values("key").unique())

    # Enforced on D−1 = keys present in that day's rows (candidates ERCOT carried),
    # bound or not. Those with no binding history in the fit universe are novel — a
    # live constraint the model has no basis to score. `[p_dm1:p_d)` is D−1's slice.
    enforced_dm1 = panel.index[p_dm1:p_d].get_level_values("key").unique()
    novel_keys = sorted(enforced_dm1.difference(universe))
    if novel_keys:
        log.info("predict_day %s: %d novel key(s) enforced D−1 with no fit history",
                 D.date(), len(novel_keys))

    score = score[score.index.get_level_values("key").isin(universe)]
    if score.empty:
        return _empty(novel_keys)

    fold = _predict_fold(train, score, arms, seed)
    wp = (fold[["p_bind", "mu_gbm"]].reset_index()
          .loc[:, ["interval_ts", "key", "p_bind", "mu_gbm"]])
    wp.attrs["novelty"] = len(novel_keys)
    wp.attrs["novel_keys"] = novel_keys
    return wp


# --------------------------------------------------------------------------
# Persisting the predictions — the input to commits 4 and 5
# --------------------------------------------------------------------------

def save_preds(path: str, preds: pd.DataFrame) -> None:
    """Write the prediction frame as a compressed .npz.

    **Not parquet:** the compute image ships neither pyarrow nor fastparquet, so
    `to_parquet` raises — and it would have raised at the END of a ~2h walk, after
    every fit was already paid for. npz needs only numpy.

    The constraint key is factorized to int32 codes against a vocabulary rather
    than stored as a string per row: at ~11M rows and ~30-char keys, the naive
    encoding is over a gigabyte of mostly-repeated text.

    Timestamps go out as int64 UTC **microseconds** — npz has no tz-aware dtype,
    and silently dropping a timezone here is exactly how an hour-shift enters a
    panel the leak audit has already signed off on. Microseconds, not nanoseconds,
    because pandas 3 makes `us` the default resolution (`date_range` returns
    `datetime64[us]` while `to_datetime(unit="ns")` returns `ns`), so an ns
    round-trip comes back with a different dtype and silently fails an index
    comparison. The data is hourly; there is no precision to lose either way.
    """
    df = preds.reset_index()
    codes, vocab = pd.factorize(df["key"], sort=True)

    def epoch_us(s: pd.Series) -> np.ndarray:
        return (pd.DatetimeIndex(s).tz_convert("UTC").tz_localize(None)
                .to_numpy("datetime64[us]").astype("int64"))

    np.savez_compressed(
        path,
        interval_ts=epoch_us(df["interval_ts"]),
        week=epoch_us(df["week"]),
        key_code=codes.astype("int32"),
        key_vocab=np.asarray(vocab, dtype=object).astype("U"),
        p_bind=df["p_bind"].to_numpy("float32"),
        mu_clim=df["mu_clim"].to_numpy("float32"),
        mu_gbm=df["mu_gbm"].to_numpy("float32"),
        y_bind=df["y_bind"].to_numpy("int8"),
        y_mu=df["y_mu"].to_numpy("float32"),   # NaN where it did not bind
    )


def load_preds(path: str) -> pd.DataFrame:
    """Inverse of `save_preds`. Round-trips exactly — see the test."""
    z = np.load(path, allow_pickle=False)
    vocab = z["key_vocab"]
    df = pd.DataFrame({
        "interval_ts": pd.to_datetime(z["interval_ts"], unit="us", utc=True),
        "key": vocab[z["key_code"]],
        "week": pd.to_datetime(z["week"], unit="us", utc=True),
        "p_bind": z["p_bind"], "mu_clim": z["mu_clim"], "mu_gbm": z["mu_gbm"],
        "y_bind": z["y_bind"], "y_mu": z["y_mu"],
    })
    return df.set_index(["interval_ts", "key"])


def _fmt_reliability(rel: pd.DataFrame) -> str:
    lines = ["  p_bin      n     said    happened     gap"]
    for b, r in rel.iterrows():
        bar = "#" * int(round(r["y_rate"] * 20))
        lines.append(f"  {b/10:.1f}-{(b+1)/10:.1f} {int(r['n']):7d} "
                     f"{r['p_mean']:7.3f} {r['y_rate']:11.3f} {r['gap']:+7.3f}  {bar}")
    return "\n".join(lines)


def spill_panel_features(panel: pd.DataFrame, spill_dir: str) -> pd.DataFrame:
    """Rewrite the panel's float32 feature block as a memory-mapped Arrow file.

    The covariate columns are ~3.9 GB and resident for the whole walk. Held as a
    numpy block they are anonymous RAM the node can only reclaim by OOM-killing the
    process; written to an Arrow IPC file on the disk PVC and reopened via
    `pa.memory_map` + `ArrowDtype`, they become CLEAN file-backed page cache the node
    evicts under pressure and re-faults on demand — the reclaimability the bind
    matrix gets from `_alloc_bind_matrix`, applied to the resident panel itself.

    Zero-copy and value-preserving, both verified on this stack: HistGBM (both
    heads), the raw `to_numpy` reads that fill the bind matrix, `np.digitize` /
    `np.quantile` in the climatology, and the target-encoding groupby all consume
    `ArrowDtype` columns with results bit-identical to the numpy panel — NaN
    covariate holes included, so HistGBM's native-missing handling is unchanged.
    Only the feature columns move; the NaN-bearing `y_mu` target and the `y_bind`
    label stay numpy exactly as the walk and the leak audit expect them.

    Guarded: the one-time `from_pandas` copy briefly coexists with the numpy panel
    (~8 GB, below `build_panel`'s own peak, so a run that built the panel can spill
    it). And if the Arrow wrap does not stay file-backed — a future pandas/pyarrow
    could materialise it into anonymous RAM — the spill has bought nothing, so we
    log and hand back the in-RAM panel rather than pay disk I/O for no benefit.
    """
    import pyarrow as pa

    feat = [c for c in panel.columns
            if c not in NON_FEATURES and not c.startswith("vintage_")]
    if not feat:
        return panel
    os.makedirs(spill_dir, exist_ok=True)
    path = os.path.join(spill_dir, _PANEL_FILE)

    # One record batch => single-chunk columns, so later `iloc` slices never pay to
    # combine chunks. `preserve_index=False`: the MultiIndex is reattached below.
    table = pa.Table.from_pandas(panel[feat], preserve_index=False)
    with pa.ipc.new_file(path, table.schema) as w:
        w.write_table(table, max_chunksize=len(panel) or 1)
    del table

    base = pa.total_allocated_bytes()
    mapped = pa.ipc.open_file(pa.memory_map(path, "r")).read_all()
    adf = mapped.to_pandas(types_mapper=pd.ArrowDtype)
    adf.index = panel.index
    for c in panel.columns:
        if c not in feat:            # y_mu / y_bind / delivery_day stay numpy
            adf[c] = panel[c].to_numpy()
    adf = adf[list(panel.columns)]   # restore original column order

    grew_gb = (pa.total_allocated_bytes() - base) / 1e9
    if grew_gb > 0.1:
        log.warning("panel spill did not stay file-backed (+%.2f GB anonymous); "
                    "keeping the in-RAM panel", grew_gb)
        return panel

    log.info("panel features spilled to %s — %d cols now Arrow-mmap file-backed",
             path, len(feat))
    return adf


def main(argv: list[str] | None = None) -> int:
    import argparse

    import psycopg

    from compute.mu.features import build_panel
    from compute.sf.panels import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", default="2024-12-11", help="first day of data read")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--score-from", default=None,
                   help="first scored week (default: first available boundary)")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--policy", default="active_28d", choices=["active_28d", "all"])
    p.add_argument("--features", default="all", choices=sorted(FEATURE_SETS),
                   help="ablation arm (plan/0088): which covariate families the "
                        "model may see. The panel is built identically either way.")
    p.add_argument("--out", default=None, help="write weekly metrics CSV here")
    p.add_argument("--preds-out", default=None,
                   help="write per-row predictions .npz here (commit 4/5 input)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    score_from_ts = (pd.Timestamp(args.score_from, tz="UTC")
                     if args.score_from else None)
    arms = arms_for(args.features)

    with psycopg.connect(dsn) as conn:
        log.info("loading shadow prices %s → %s", lo.date(), hi.date())
        M = load_shadow_prices(conn, lo, hi)
        # The congestion panel is loaded only for the geography arm — it is what
        # `SF` is fitted against. Skipping it when no arm needs it keeps the base
        # run identical to 0085's and saves a large read.
        C = None
        if "geo" in arms:
            C = load_congestion_panel(conn, lo, hi)
            log.info("C = %s (geography arm is on)", C.shape)
        log.info("M = %s; building covariate panel (policy=%s)", M.shape, args.policy)
        panel = build_panel(conn, M, lo, hi, policy=args.policy, C=C,
                            score_from=score_from_ts,
                            with_weather="wx" in arms)

    log.info("panel = %s rows x %s cols, %.2f GB — arm %r sees %d features",
             f"{len(panel):,}", panel.shape[1],
             panel.memory_usage(deep=False).sum() / 1e9, args.features,
             len(feature_cols(panel, arms)) + 1)

    # Resolve the disk spill directory once — both spills share it: the disk-backed
    # --preds-out PVC by default, MU_SPILL_DIR overrides.
    spill_dir = os.environ.get("MU_SPILL_DIR")
    if spill_dir is None and args.preds_out:
        spill_dir = os.path.join(
            os.path.dirname(os.path.abspath(args.preds_out)) or ".", "spill")

    # The per-fold bind matrix always spills when a dir is available (the ~3.4 GB
    # float64 train matrix — see _alloc_bind_matrix). The resident panel is a larger,
    # opt-in spill (pyarrow): enabled by MU_SPILL_PANEL for nodes whose headroom can
    # dip mid-run, off by default so the common path keeps the fast in-RAM panel.
    if spill_dir:
        log.info("bind matrix spills to disk at %s", spill_dir)
        if os.environ.get("MU_SPILL_PANEL"):
            panel = spill_panel_features(panel, spill_dir)

    # Anchor on the SHADOW-PRICE panel's first day so the scored weeks coincide
    # with sf/eval's — see refit_boundaries.
    preds, weekly = walk_forward(panel, args.train_days, args.refit_days,
                                 score_from_ts, anchor=M.index[0].normalize(),
                                 arms=arms, spill_dir=spill_dir)

    # Unlink the on-disk panel copy; the mmap stays valid until this process exits.
    if spill_dir:
        try:
            os.remove(os.path.join(spill_dir, _PANEL_FILE))
        except OSError:
            pass

    if weekly.empty:
        print("no scorable weeks")
        return 1

    y = preds["y_bind"].to_numpy()
    pr = preds["p_bind"].to_numpy()
    pooled = bind_metrics(y, pr)

    print(f"\n=== HEAD 1: P(bind) — calibration first === [arm: {args.features}]")
    print(f"  weeks {len(weekly)}   rows {len(preds):,}   "
          f"base rate {pooled['base_rate']:.4f}   mean pred {pooled['mean_pred']:.4f}")
    print(f"  Brier {pooled['brier']:.5f}   ECE {pooled['ece']:.4f}   "
          f"AUC {pooled['auc']:.4f}")
    print("\n  reliability curve (said vs happened):")
    print(_fmt_reliability(reliability(y, pr)))

    hit = preds[preds["y_bind"] == 1]
    print("\n=== HEAD 2: E[mu | bind] ===")
    print(f"  binding rows {len(hit):,}   mean mu ${hit['y_mu'].mean():.2f}")
    for name in ("mu_clim", "mu_gbm"):
        mae = float((hit[name] - hit["y_mu"]).abs().mean())
        print(f"  {name:8s} MAE ${mae:7.2f}   "
              f"weekly R2 {weekly[f'r2_{name}'].mean():+.3f}")
    print(f"\n  VERDICT: {mu_head_verdict(weekly)}")

    if args.out:
        weekly.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")
    if args.preds_out:
        save_preds(args.preds_out, preds)
        print(f"wrote {args.preds_out}")
    return 0


def mu_head_verdict(weekly: pd.DataFrame) -> str:
    """Which head-2 wins? The plan says climatology unless the GBM beats it.

    Stated as a function so the answer is recorded rather than assumed. A tie goes
    to the climatology: it is simpler, and the plan pre-registered it as the
    backbone.
    """
    if weekly.empty or "mae_mu_gbm" not in weekly:
        return "climatology (no comparison available)"
    clim, gbm = weekly["mae_mu_clim"].mean(), weekly["mae_mu_gbm"].mean()
    better = weekly["mae_mu_gbm"] < weekly["mae_mu_clim"]
    if gbm < clim:
        return (f"GBM (MAE {gbm:.2f} vs climatology {clim:.2f}; "
                f"wins {int(better.sum())}/{len(weekly)} weeks)")
    return (f"climatology (MAE {clim:.2f} vs GBM {gbm:.2f}; "
            f"GBM wins only {int(better.sum())}/{len(weekly)} weeks)")


if __name__ == "__main__":
    raise SystemExit(main())
