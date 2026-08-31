"""The two heads: P(bind) and E[mu | bind].

**Pooled, not per-constraint.** One model over all constraints, with constraint
identity entering as *features* (its own binding history, plus a target-encoded
binding rate) rather than as N separate models.

**Head 1 — P(bind at h).** Gradient-boosted classifier.

**Head 2 — E[mu | bind].** A gradient-boosted regressor predicts conditional
severity from the causal feature panel.

`_predict_fold` is shared by daily serving and historical backtests.

"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

import numpy as np
import pandas as pd
from compute.artifacts import DEFAULT_RUNS_ROOT, RunArtifacts
from compute.mu_forecast.model.artifacts import combine_pred_chunks, load_preds, save_preds
from compute.mu_forecast.model.heads import (alloc_bind_matrix as _alloc_bind_matrix,
                                             apply_encoding, bind_metrics, fit_bind_head,
                                             fit_mu_head, fold_matrix, predict_mu_head,
                                             reliability, target_encoding)
from compute.time import ERCOT_TZ, ct_day_bounds
from compute.sf_map.config import REFIT_DAYS, WINDOW_DAYS

log = logging.getLogger("compute.mu_forecast.model.runner")

# Semantic aliases retain the μ forecast vocabulary for callers while sharing
# the SF operating point that fixes the scored-week boundaries.
DEFAULT_TRAIN_DAYS = WINDOW_DAYS
DEFAULT_REFIT_DAYS = REFIT_DAYS

# buffer for training days, ensure extra data exists behind a training window
PANEL_LEADIN_DAYS = 7

# Columns that are targets or bookkeeping, never inputs.
NON_FEATURES = ("y_mu", "y_bind", "delivery_day")

# Smoothing for the target encoding. A constraint seen for 3 hours should not be
# handed a 1.0 binding rate; it should be pulled most of the way back to the pooled
# mean. `n / (n + PRIOR_STRENGTH)` is the weight its own history gets.
PRIOR_STRENGTH = 50.0

MU_FLOOR = 1.0   # $/MWh; log1p is taken on mu, so this only guards the tail

# The on-disk bind matrix (see `_alloc_bind_matrix`). One fixed file, reused every
# fold, so at most one ~3.4 GB matrix is ever on the PVC; the walk unlinks it.
BIND_MATRIX_FILE = "bind_matrix.f64"

# The on-disk Arrow copy of the panel's feature block (see `spill_panel_features`),
# opt-in via MU_SPILL_PANEL. One file, overwritten per run, unlinked when main ends.
PANEL_FILE = "panel_features.arrow"

# Retained for tests that redirect the mounted runs PVC.
RUNS_ROOT = DEFAULT_RUNS_ROOT


def weekly_path_for(run_id: str) -> str:
    """The walk's weekly-metrics CSV for `run_id` — `runs/<run-id>/mu/mu_weekly.csv`."""
    return str(RunArtifacts(run_id, RUNS_ROOT).weekly_metrics)


def preds_path_for(run_id: str) -> str:
    """The walk's per-row predictions / residual-pool npz for `run_id` —
    `runs/<run-id>/mu/mu_preds.npz`, the path `backfill_nodal`/`daily_forecast`
    resolve from the same run id (their `preds_path_for` mirrors this)."""
    return str(RunArtifacts(run_id, RUNS_ROOT).predictions)


def resolve_output_paths(run_id: str | None, out: str | None, preds_out: str | None,
                         ) -> tuple[str | None, str | None]:
    """Derive the weekly + preds paths under `runs/<run-id>/mu/` from a run id.

    Explicit `--out` / `--preds-out` always win; a run id fills in only the paths
    the caller left unset. With no run id both stay `None` — the legacy
    explicit-only mode, unchanged.
    """
    if run_id:
        out = out or weekly_path_for(run_id)
        preds_out = preds_out or preds_path_for(run_id)
    return out, preds_out


def persist_outputs(weekly: pd.DataFrame, preds: pd.DataFrame,
                    out: str | None, preds_out: str | None) -> None:
    """Write the walk's weekly metrics and/or predictions, creating parents first.

    Each path is optional. The parent tree — `runs/<run-id>/mu/` under the derived
    convention — is created before the write, so a first run on a fresh PVC does not
    fail on a missing directory.
    """
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        weekly.to_csv(out, index=False)
        print(f"\nwrote {out}")
    if preds_out:
        os.makedirs(os.path.dirname(os.path.abspath(preds_out)) or ".", exist_ok=True)
        save_preds(preds_out, preds)
        print(f"wrote {preds_out}")


# --------------------------------------------------------------------------
# The ablation arms
# --------------------------------------------------------------------------
# Build the panel once; express an arm as a subset of its columns.
# `build_panel` materialises ~10M rows and is the peak-memory line of the
# package. Rebuilding it five times to run five arms would cost five walks'
# worth of the most expensive step in the branch.
#
# Each arm owns a column-name prefix. A new covariate joins an arm by being named
# for it.
ARM_PREFIXES = {
    "lag": "lag_",   # lagged realized mu (the persistence content)
    "geo": "geo_",   # constraint geography via the |SF| centroid
    "wx": "wx_",     # per-constraint weather-response vectors
    "out": "out_",   # per-constraint generation-outage exposure
}

# `base` is what every arm is measured against. `all` is every arm at once.
#
# The first five keys are frozen — do not edit them. out and all+out are used
# in ablation
FEATURE_SETS = {
    "base": (),
    "lag": ("lag",),
    "geo": ("geo",),
    "wx": ("wx",),
    "all": ("lag", "geo", "wx"),
    "out": ("out",),                         # outage exposure alone
    "all+out": ("lag", "geo", "wx", "out"),  # `all` + outage
}


def feature_cols(panel: pd.DataFrame, arms: tuple[str, ...] = ("lag", "geo", "wx"),
                 ) -> list[str]:
    """The feature columns for one arm.

    A column belongs to an arm iff it carries that arm's prefix; everything else
    is `base`.

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
# The walk
# --------------------------------------------------------------------------

def _predict_fold(train: pd.DataFrame, score: pd.DataFrame,
                  arms: tuple[str, ...] = ("lag", "geo", "wx"),
                  seed: int = 0, spill_dir: str | None = None) -> pd.DataFrame:
    """One fold: fit both heads on `train`, predict `score`. Predictions only.

    `spill_dir`, when given, puts the float64 bind matrix on that disk PVC instead
    of anonymous RAM (see `_alloc_bind_matrix`) — the walk's peak-memory line.

    Returns one row per scored `(interval_ts, key)` with `p_bind` and `mu_gbm`,
    indexed by `score`'s index. The realized `y_bind`/`y_mu` join
    stays with the caller that holds the labels.

    """
    feat = feature_cols(train, arms)
    cols = feat + ["key_bind_rate"]
    keep = feat + ["y_bind", "y_mu"]

    # `target_encoding`: historic "default" bind rate
    # `apply_encoding` only *adds* one column - `key_bind_rate`, (bind per constraint)
    # *_e:  "encoded" - added the bind_rate
    # *_tr: "training"

    enc, pooled = target_encoding(train)
    score_e = apply_encoding(score, enc, pooled, keep)

    # Never materialise the full-width float32 fold copy. On the wide `all` arm
    # (86 features) that copy is ~1.7 GB and it has to coexist with the ~3.3 GB
    # float64 bind matrix while the matrix is filled.
    binders_e = apply_encoding(train[train["y_bind"] == 1], enc, pooled, keep)
    y_bind_tr = train["y_bind"].to_numpy()

    key_rate = enc.reindex(
        train.index.get_level_values("key")).fillna(pooled).to_numpy("float32")

    # x_tr: binding classifier’s training feature matrix: all selected features plus key_rate
    x_tr = _alloc_bind_matrix((len(train), len(cols)), spill_dir)

    for j, c in enumerate(feat):
        x_tr[:, j] = train[c].to_numpy()
    x_tr[:, len(feat)] = key_rate  # last column of `cols`; float32 → float64
    if isinstance(x_tr, np.memmap):
        x_tr.flush()  # msync the just-written 3.4 GB: dirty pages count as
                      # unreclaimable against the node/cgroup, clean ones it can
                      # evict — the flush is what averts the OOM, not the move alone.

    #
    # cols: features + key_bind_rate
    #
    # p_bind HistGradientBoostingClassifier model.fit()
    #
    bind = fit_bind_head(x_tr, y_bind_tr, seed)
    del x_tr, y_bind_tr, key_rate
    p = bind.predict_proba(fold_matrix(score_e, cols))[:, 1]

    # Conditional severity head: E[μ | bind].
    mu_gbm = predict_mu_head(fit_mu_head(binders_e, cols, seed), score_e, cols)

    return pd.DataFrame({"p_bind": p, "mu_gbm": mu_gbm}, index=score_e.index)


# Forward inference — one fold, prediction block = a single delivery day
# --------------------------------------------------------------------------

def predict_day(panel: pd.DataFrame, D: pd.Timestamp,
                *, train_days: int = DEFAULT_TRAIN_DAYS,
                arms: tuple[str, ...] = ("lag", "geo", "wx"),
                seed: int = 0, spill_dir: str | None = None) -> pd.DataFrame:
    """Fit both heads on the trailing window and predict delivery day `D`.

    This is `walk_forward`'s fold (`_predict_fold`) with `train` = `[D −
    train_days, D)`, `score` = the 24 hours of `[D, D+1d)`.

    `spill_dir`, puts the fold's ~3.4 GB float64 bind matrix on that disk PVC
    instead of anonymous RAM.

    **Novelty** is the number of keys that the fit never saw bind.
    `wp.attrs["novelty"]` / `wp.attrs["novel_keys"]` is logged, for summary to
    widen bands or flag rather than silently zero them.

    Returns `wp` = `(interval_ts, key, p_bind, mu_gbm)` the flat frame that
    `propagate_window` consumes; realized labels are dropped from the served
    shape (propagation reads `p_bind` and `mu_gbm` only).

    """
    ts = panel.index.get_level_values("interval_ts")
    if not ts.is_monotonic_increasing:
        raise ValueError("panel must be sorted by interval_ts")
    D = pd.Timestamp(D)
    D = D.tz_localize(ts.tz) if D.tz is None else D.tz_convert(ts.tz)

    ct_date = D.tz_convert(ERCOT_TZ).date()
    D, hi = (pd.Timestamp(b).tz_convert(ts.tz) for b in ct_day_bounds(ct_date))
    dm1, _ = ct_day_bounds(ct_date - timedelta(days=1))
    dm1 = pd.Timestamp(dm1).tz_convert(ts.tz)

    def _empty(novel_keys: list[str]) -> pd.DataFrame:
        out = pd.DataFrame(columns=["interval_ts", "key", "p_bind", "mu_gbm"])
        out.attrs["novelty"] = len(novel_keys)
        out.attrs["novel_keys"] = novel_keys
        return out

    lo = D - pd.Timedelta(days=train_days)

    # p: position
    # p_lo: first row at D - train_days
    # p_dm1: first row of CT day D−1
    # p_d: first row of CT day D
    # p_hi: first row after CT day D (the next CT midnight)
    # subdividing the panel between train and forecast date ranges
    p_lo, p_dm1, p_d, p_hi = ts.searchsorted([lo, dm1, D, hi], side="left")
    train, score = panel.iloc[p_lo:p_d], panel.iloc[p_d:p_hi]
    if train.empty or score.empty:
        return _empty([])

    universe = pd.Index(
        train.index[train["y_bind"] == 1].get_level_values("key").unique())

    # Enforced on D−1 = keys present in that day's rows (candidates ERCOT
    # carried), bound or not. Those with no binding history in the fit universe
    # are novel — a live constraint the model has no basis to score.
    # `[p_dm1:p_d)` is D−1's slice.
    enforced_dm1 = panel.index[p_dm1:p_d].get_level_values("key").unique()
    novel_keys = sorted(enforced_dm1.difference(universe))
    if novel_keys:
        log.info("predict_day %s: %d novel key(s) enforced D−1 with no fit history",
                 D.date(), len(novel_keys))

    score = score[score.index.get_level_values("key").isin(universe)]
    if score.empty:
        return _empty(novel_keys)

    #
    # predict_fold is where actual prediction, model.fit/predict occurs
    #
    fold = _predict_fold(train, score, arms, seed, spill_dir)

    # Drop the on-disk bind matrix so a per-day backfill loop does not leave a
    # stale ~3.4 GB file on the PVC.
    if spill_dir is not None:
        try:
            os.remove(os.path.join(spill_dir, BIND_MATRIX_FILE))
        except OSError:
            pass
    wp = (fold[["p_bind", "mu_gbm"]].reset_index()
          .loc[:, ["interval_ts", "key", "p_bind", "mu_gbm"]])
    wp.attrs["novelty"] = len(novel_keys)
    wp.attrs["novel_keys"] = novel_keys
    return wp


# --------------------------------------------------------------------------
# Persisting the predictions
# --------------------------------------------------------------------------

def spill_panel_features(panel: pd.DataFrame, spill_dir: str) -> pd.DataFrame:
    """Rewrite the panel's float32 feature block as a memory-mapped Arrow file.

    """
    import pyarrow as pa

    feat = [c for c in panel.columns
            if c not in NON_FEATURES and not c.startswith("vintage_")]
    if not feat:
        return panel
    os.makedirs(spill_dir, exist_ok=True)
    path = os.path.join(spill_dir, PANEL_FILE)

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
