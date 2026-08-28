"""The two heads: P(bind) and E[mu | bind].

**Pooled, not per-constraint.** One model over all constraints, with constraint
identity entering as *features* (its own binding history, plus a target-encoded
binding rate) rather than as N separate models.

**Head 1 — P(bind at h).** Gradient-boosted classifier.

**Head 2 — E[mu | bind].** The plan says conditional climatology FIRST, quantile
regression only if the simple version is beaten — so both are built and scored
head-to-head here, and `mu_head` reports which won rather than assuming. The
climatology is bucketed on net load, which is the physical driver: congestion
magnitude is a function of how hard the system is being pushed.

**walk-forward.** Train on the trailing window ending STRICTLY BEFORE the
scored week — the same convention as `sf/eval.evaluate`.

"""
from __future__ import annotations

import gc
import logging
import os
import time
from datetime import timedelta

import numpy as np
import pandas as pd
from compute.artifacts import DEFAULT_RUNS_ROOT, RunArtifacts
from compute.mu_forecast.model.artifacts import combine_pred_chunks, save_preds
from compute.mu_forecast.model.heads import (alloc_bind_matrix as _alloc_bind_matrix,
                                             apply_encoding, bind_metrics, fit_bind_head,
                                             fit_mu_climatology, fit_mu_head, fold_matrix,
                                             predict_mu_climatology, predict_mu_head,
                                             reliability, target_encoding)
from compute.mu_forecast.model.scheduling import refit_boundaries, score_chunks
from compute.time import ERCOT_TZ, ct_day_bounds
from compute.sf_map.config import REFIT_DAYS, WINDOW_DAYS

log = logging.getLogger("compute.mu_forecast.model.runner")

# Semantic aliases retain the μ forecast vocabulary for callers while sharing
# the SF operating point that fixes the scored-week boundaries.
DEFAULT_TRAIN_DAYS = WINDOW_DAYS
DEFAULT_REFIT_DAYS = REFIT_DAYS

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
_BIND_MATRIX_FILE = "bind_matrix.f64"

# The on-disk Arrow copy of the panel's feature block (see `spill_panel_features`),
# opt-in via MU_SPILL_PANEL. One file, overwritten per run, unlinked when main ends.
_PANEL_FILE = "panel_features.arrow"

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

    Returns one row per scored `(interval_ts, key)` with `p_bind`, `mu_clim`,
    `mu_gbm`, indexed by `score`'s index. The realized `y_bind`/`y_mu` join
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
    clim_e = train[["net_load", "hour", "y_mu", "y_bind"]].copy()   # climatology
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

    # climatology: historic baseline from typical conditions
    # edges: quantiles of net load; divide training net_load into buckets.
    # cells: avg mu when bound, per (net-load bucket, hour)
    # grand: fallback avg mu when no (bucket, hour) observation
    cells, edges, grand = fit_mu_climatology(clim_e)
    mu_clim = predict_mu_climatology(score_e, cells, edges, grand)

    # prob mu HistGradientBoostingRegressor NB: fit and predict
    # "gmb" gradient boosted mu E[mu]
    mu_gbm = predict_mu_head(fit_mu_head(binders_e, cols, seed), score_e, cols)

    return pd.DataFrame(
        {"p_bind": p, "mu_clim": mu_clim, "mu_gbm": mu_gbm}, index=score_e.index)


def walk_forward(panel: pd.DataFrame,
                 train_days: int = DEFAULT_TRAIN_DAYS,
                 refit_days: int = DEFAULT_REFIT_DAYS,
                 score_from: pd.Timestamp | None = None,
                 score_until: pd.Timestamp | None = None,
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
    if score_until is not None:
        starts = starts[starts < pd.Timestamp(score_until)]
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
    `propagate_window` consumes; `mu_clim` and the realized labels are dropped
    from the served shape (propagation reads `p_bind` and `mu_gbm` only).

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
            os.remove(os.path.join(spill_dir, _BIND_MATRIX_FILE))
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

def _fmt_reliability(rel: pd.DataFrame) -> str:
    lines = ["  p_bin      n     said    happened     gap"]
    for b, r in rel.iterrows():
        bar = "#" * int(round(r["y_rate"] * 20))
        lines.append(f"  {b/10:.1f}-{(b+1)/10:.1f} {int(r['n']):7d} "
                     f"{r['p_mean']:7.3f} {r['y_rate']:11.3f} {r['gap']:+7.3f}  {bar}")
    return "\n".join(lines)


def spill_panel_features(panel: pd.DataFrame, spill_dir: str) -> pd.DataFrame:
    """Rewrite the panel's float32 feature block as a memory-mapped Arrow file.

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


def walk_forward_chunked(build_panel_for_range, *, score_from: pd.Timestamp,
                         end: pd.Timestamp, train_days: int, refit_days: int,
                         chunk_weeks: int, arms: tuple[str, ...],
                         spill_dir: str | None, chunk_dir: str,
                         ) -> tuple[pd.DataFrame, list[str]]:
    """Build, score, and release bounded historical panel chunks.

    Each chunk reads the score window plus its full causal training margin; only
    that chunk's predictions are held in RAM, then saved as a standard NPZ piece.
    ``combine_pred_chunks`` subsequently produces the canonical single artifact.
    """
    windows = score_chunks(score_from, end, refit_days, chunk_weeks)
    os.makedirs(chunk_dir, exist_ok=True)
    weekly_parts: list[pd.DataFrame] = []
    paths: list[str] = []
    for i, (chunk_start, chunk_end) in enumerate(windows, start=1):
        read_start = chunk_start - pd.Timedelta(days=train_days + PANEL_LEADIN_DAYS)
        log.info("chunk %d/%d: scores %s → %s; reads from %s",
                 i, len(windows), chunk_start.date(),
                 (chunk_end - pd.Timedelta(days=refit_days)).date(), read_start.date())
        panel = build_panel_for_range(read_start, chunk_end)
        try:
            log.info("chunk %d/%d: panel = %s rows x %s cols", i, len(windows),
                     f"{len(panel):,}", panel.shape[1])
            if spill_dir and os.environ.get("MU_SPILL_PANEL"):
                panel = spill_panel_features(panel, spill_dir)
            preds, weekly = walk_forward(
                panel, train_days, refit_days, chunk_start, chunk_end,
                arms=arms, spill_dir=spill_dir,
            )
            path = os.path.join(chunk_dir, f"preds-{i:04d}.npz")
            save_preds(path, preds)
            paths.append(path)
            weekly_parts.append(weekly)
            log.info("chunk %d/%d: wrote %s prediction rows", i, len(windows),
                     f"{len(preds):,}")
            del preds
        finally:
            del panel
            if spill_dir:
                try:
                    os.remove(os.path.join(spill_dir, _PANEL_FILE))
                except OSError:
                    pass
            gc.collect()
    return (pd.concat(weekly_parts, ignore_index=True) if weekly_parts
            else pd.DataFrame()), paths


def main(argv: list[str] | None = None) -> int:
    import argparse

    import psycopg

    from compute.mu_forecast.panel.build import build_panel
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", default=None,
                   help="series origin: the first scored week (SAME meaning as "
                        "weekly_map/eval --start). The data-read floor is derived "
                        "as start − train_days − leadin; do NOT pass a data floor.")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--score-from", default=None,
                   help="override the scored-grid phase; defaults to --start. Rarely "
                        "needed — only to pin a phase different from the origin.")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--policy", default="active_28d", choices=["active_28d", "all"])
    p.add_argument("--features", default="all", choices=sorted(FEATURE_SETS),
                   help="ablation arm (plan/0088): which covariate families the "
                        "model may see. The panel is built identically either way.")
    p.add_argument("--chunk-weeks", type=int, default=32,
                   help="build and score this many weekly folds at a time, writing "
                        "temporary prediction chunks to bound full-history memory; "
                        "0 opts into the legacy single-panel walk")
    p.add_argument("--run-id", default=None,
                   help="canonical run namespace (plan/0113): derive --out and "
                        "--preds-out under runs/<run-id>/mu/ (mu_weekly.csv, "
                        "mu_preds.npz) unless either is passed explicitly")
    p.add_argument("--out", default=None, help="write weekly metrics CSV here "
                                               "(overrides the --run-id path)")
    p.add_argument("--preds-out", default=None,
                   help="write per-row predictions .npz here (commit 4/5 input); "
                        "overrides the --run-id path")
    args = p.parse_args(argv)

    # A run id derives both outputs under runs/<run-id>/mu/; explicit flags win.
    args.out, args.preds_out = resolve_output_paths(
        args.run_id, args.out, args.preds_out)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # --start is the SERIES ORIGIN (first scored week), the same meaning it carries
    # in weekly_map/eval. --score-from overrides only the grid phase, defaulting to
    # the origin — so a single date drives all three stages.
    origin = args.score_from or args.start
    if origin is None:
        p.error("pass --start (the series origin / first scored week)")
    # CT, matching `lo`/`hi` below and `predict_day`'s CT anchor (0133) — `origin`
    # is a bare `YYYY-MM-DD` naming a CT calendar date, and `tz="UTC"` here used to
    # read the SAME string as a different instant (UTC midnight, not CT midnight)
    # than the read-floor did, desyncing the refit grid's phase from the CT day
    # boundary `predict_day`/`forecast_day` now score on.
    score_from_ts = pd.Timestamp(origin, tz="America/Chicago")
    if args.chunk_weeks < 0:
        p.error("--chunk-weeks must be non-negative")
    if args.chunk_weeks and not args.preds_out:
        p.error("--chunk-weeks requires --run-id or --preds-out for the final artifact")

    # Derive the data-read floor from the origin: the walk needs train_days of history
    # behind the first scored week, plus PANEL_LEADIN_DAYS of slack for the panel's
    # front-edge day-loss. This never shifts the scored grid (pinned by score_from);
    # it only guarantees the first fold gets its full trailing window.
    lo = (pd.Timestamp(origin, tz="America/Chicago")
          - pd.Timedelta(days=args.train_days + PANEL_LEADIN_DAYS))
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    arms = arms_for(args.features)

    # Resolve the disk spill directory once — both spills share it: the disk-backed
    # --preds-out PVC by default, MU_SPILL_DIR overrides.
    spill_dir = os.environ.get("MU_SPILL_DIR")
    if spill_dir is None and args.preds_out:
        spill_dir = os.path.join(
            os.path.dirname(os.path.abspath(args.preds_out)) or ".", "spill")

    if spill_dir:
        log.info("bind matrix spills to disk at %s", spill_dir)

    if args.chunk_weeks:
        chunk_dir = os.path.join(
            spill_dir or os.path.dirname(os.path.abspath(args.preds_out)),
            "mu-pred-chunks",
        )
        with psycopg.connect(dsn) as conn:
            def build_chunk(read_start, chunk_end):
                log.info("loading chunk inputs %s → %s", read_start.date(),
                         chunk_end.date())
                M = load_shadow_prices(conn, read_start, chunk_end)
                C = None
                if "geo" in arms:
                    C = load_congestion_panel(conn, read_start, chunk_end)
                    log.info("chunk C = %s", C.shape)
                panel = build_panel(conn, M, read_start, chunk_end,
                                    policy=args.policy, C=C,
                                    score_from=score_from_ts,
                                    with_weather="wx" in arms)
                del M, C
                return panel

            weekly, chunk_paths = walk_forward_chunked(
                build_chunk, score_from=score_from_ts, end=hi,
                train_days=args.train_days, refit_days=args.refit_days,
                chunk_weeks=args.chunk_weeks, arms=arms, spill_dir=spill_dir,
                chunk_dir=chunk_dir,
            )
        n_pred_rows = combine_pred_chunks(chunk_paths, args.preds_out)
        for path in chunk_paths:
            os.remove(path)
        try:
            os.rmdir(chunk_dir)
        except OSError:
            pass
        preds = None
        log.info("combined %d prediction chunks into %s (%s rows)",
                 len(chunk_paths), args.preds_out, f"{n_pred_rows:,}")
    else:
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
            anchor = M.index[0].normalize()
            del M, C

        log.info("panel = %s rows x %s cols, %.2f GB — arm %r sees %d features",
                 f"{len(panel):,}", panel.shape[1],
                 panel.memory_usage(deep=False).sum() / 1e9, args.features,
                 len(feature_cols(panel, arms)) + 1)
        if spill_dir and os.environ.get("MU_SPILL_PANEL"):
            panel = spill_panel_features(panel, spill_dir)

        # Anchor on the SHADOW-PRICE panel's first day so the scored weeks coincide
        # with sf/eval's — see refit_boundaries.
        preds, weekly = walk_forward(panel, args.train_days, args.refit_days,
                                     score_from_ts, anchor=anchor,
                                     arms=arms, spill_dir=spill_dir)
        del panel
        if spill_dir:
            try:
                os.remove(os.path.join(spill_dir, _PANEL_FILE))
            except OSError:
                pass

    if weekly.empty:
        print("no scorable weeks")
        return 1

    print(f"\n=== HEAD 1: P(bind) — calibration first === [arm: {args.features}]")
    if preds is None:
        print(f"  weeks {len(weekly)}   rows {n_pred_rows:,}   "
              "(chunked; pooled calibration is in the prediction artifact)")
        print(f"  weekly mean Brier {weekly['brier'].mean():.5f}   "
              f"ECE {weekly['ece'].mean():.4f}   AUC {weekly['auc'].mean():.4f}")
    else:
        y = preds["y_bind"].to_numpy()
        pr = preds["p_bind"].to_numpy()
        pooled = bind_metrics(y, pr)
        print(f"  weeks {len(weekly)}   rows {len(preds):,}   "
              f"base rate {pooled['base_rate']:.4f}   mean pred {pooled['mean_pred']:.4f}")
        print(f"  Brier {pooled['brier']:.5f}   ECE {pooled['ece']:.4f}   "
              f"AUC {pooled['auc']:.4f}")
        print("\n  reliability curve (said vs happened):")
        print(_fmt_reliability(reliability(y, pr)))

    print("\n=== HEAD 2: E[mu | bind] ===")
    if preds is None:
        print("  chunked; values below are weekly means")
    else:
        hit = preds[preds["y_bind"] == 1]
        print(f"  binding rows {len(hit):,}   mean mu ${hit['y_mu'].mean():.2f}")
    for name in ("mu_clim", "mu_gbm"):
        mae = (float((hit[name] - hit["y_mu"]).abs().mean())
               if preds is not None else float(weekly[f"mae_{name}"].mean()))
        print(f"  {name:8s} MAE ${mae:7.2f}   "
             f"weekly R2 {weekly[f'r2_{name}'].mean():+.3f}")
    print(f"\n  VERDICT: {mu_head_verdict(weekly)}")

    persist_outputs(weekly, preds if preds is not None else pd.DataFrame(),
                    args.out, None if preds is None else args.preds_out)
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
