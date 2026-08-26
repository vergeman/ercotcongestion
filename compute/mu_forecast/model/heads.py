"""Fitting and prediction primitives for the μ model's two heads."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, roc_auc_score

PRIOR_STRENGTH = 50.0
MU_FLOOR = 1.0
BIND_MATRIX_FILE = "bind_matrix.f64"


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

    Toy working example to visualize commands below.

train:
                                              net_load  hour       y_mu  y_bind
interval_ts               key
2025-07-01 00:00:00+00:00 north_line  52001.845230     0        NaN       0
                          west_line   52001.845230     0        NaN       0
                          coast_line  52001.845230     0        NaN       0
2025-07-01 01:00:00+00:00 north_line  55553.946847     1        NaN       0
                          west_line   55553.946847     1  20.390796       1
...                                            ...   ...        ...     ...
2025-08-09 22:00:00+00:00 west_line   47212.614390    22        NaN       0
                          coast_line  47212.614390    22        NaN       0
2025-08-09 23:00:00+00:00 north_line  48416.955499    23        NaN       0
                          west_line   48416.955499    23        NaN       0
                          coast_line  48416.955499    23        NaN       0

    return per key hours soothed k / n, and pooled_rate
    "smoothed fraction of hours each key bound, one value per key."

    key
    coast_line    0.295593
    north_line    0.387672
    west_line     0.489652
    Name: y_bind, dtype: float32
    """
    grouped = train.groupby(level="key")["y_bind"]

    # n: count: num of rows (bind + non-bind) - "trials"
    # k: sum: # of bind hours - "successes"
    # n,k are Series, grouped by key.
    #
    # (Pdb) grouped.sum()
    # key
    # coast_line    279
    # north_line    372
    # west_line     475
    # Name: y_bind, dtype: int64

    n, k = grouped.count(), grouped.sum()

    # mean() = sum() / count
    # total binding hours / total hours, per constraint
    # pooled: pools all the rows together - notime, no key distinction - just y_bind
    # pooled here is a single value (not grouped)
    pooled = float(train["y_bind"].mean()) if len(train) else 0.0

    # returning a smoothed result
    # not smoothed: return (k / n) binding hours / total hours
    # smoothing: add PRIOR_STRENGTH - ghost rows to add extra observations of
    # binding / total
    #
    # when adding PRIOR_STRENGTH * pooled - apply same binding percentage to
    # extra obsevations why, because when k and n is small, we get biased
    # binding. If sample is large, the k gets swallowed up in total. each n and
    # k get's
    return ((k + PRIOR_STRENGTH * pooled) / (n + PRIOR_STRENGTH)).astype("float32"), pooled


def apply_encoding(panel: pd.DataFrame, enc: pd.Series, pooled: float,
                   columns: list[str] | None = None) -> pd.DataFrame:
    """Attach the target-encoded `key_bind_rate`, on a copy of the fold.
    """
    out = (panel if columns is None else panel[columns]).copy()
    keys = out.index.get_level_values("key")
    out["key_bind_rate"] = enc.reindex(keys).fillna(pooled).to_numpy("float32")
    return out


def fold_matrix(frame: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """A feature matrix as float64, built column by column into a pre-allocated
    F-order array. HistGBM upcasts X to float64 for binning regardless of input
    dtype — there is no float32 path — so handing it the float64 directly changes no
    value. Used for the scored week (small); the train-side bind matrix is filled
    inline in `walk_forward` straight from the panel view to skip the wide float32
    fold copy the wide `all` arm cannot afford. F-order matches HistGBM's binning.
    """
    x = np.empty((len(frame), len(cols)), dtype=np.float64, order="F")
    for j, col in enumerate(cols):
        x[:, j] = frame[col].to_numpy()
    return x


def alloc_bind_matrix(shape: tuple[int, int], spill_dir: str | None) -> np.ndarray:
    """The fold's float64 bind matrix — on the disk PVC when `spill_dir` is given.

    This is the single largest live allocation in the walk: `n_train × (n_feat+1)`
    float64, ~3.4 GB on the wide `all` arm late in the walk, and it MUST coexist
    with the ~4.3 GB resident panel while `fit_bind_head` bins it. As two anonymous
    allocations that is ~8 GB the node can only reclaim by OOM-killing the process.

    Backed by a flushed `np.memmap` on the disk PVC instead, the matrix is clean
    file-backed page cache: under memory pressure the node evicts it rather than
    killing the fit. The caller fills every cell, so values are bit-identical to
    `np.empty` and `compare_base`/determinism are unaffected. F-order matches
    HistGBM's binning.

    `spill_dir=None` keeps the in-RAM allocation — the path tests and the small
    daily `predict_day` fold take, where the matrix is not worth a disk round-trip.
    """
    if spill_dir is None:
        return np.empty(shape, dtype=np.float64, order="F")
    os.makedirs(spill_dir, exist_ok=True)
    return np.memmap(os.path.join(spill_dir, BIND_MATRIX_FILE), dtype=np.float64,
                     mode="w+", shape=shape, order="F")


def fit_bind_head(x: np.ndarray, y: np.ndarray,
                  seed: int = 0) -> HistGradientBoostingClassifier:
    """Histogram Gradient-boosted classifier. NaN goes in natively — see
    `build_panel`'s note on why the covariate holes must not be filled. `x` is
    the fold's float64 feature matrix from `fold_matrix`, built by the caller
    so the float32 fold copy is freed before this fit; positional columns, so
    the caller keeps `cols` order stable.

    """
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
    what tells you whether the downstream bands are trustworthy at the high-p end.
    """
    edges = np.linspace(0, 1, n_bins + 1)
    bins = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    out = pd.DataFrame({"bin": bins, "p": p, "y": y}).groupby("bin").agg(
        n=("y", "size"), p_mean=("p", "mean"), y_rate=("y", "mean"))
    out["gap"] = out["y_rate"] - out["p_mean"]
    return out


def bind_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    """Calibration first, discrimination second — deliberately in that order."""
    rel = reliability(y, p)
    # Weight each bin's miscalibration by how much of the mass sits in it.
    return {
        "brier": float(brier_score_loss(y, p)),
        "ece": float((rel["n"] / rel["n"].sum() * rel["gap"].abs()).sum()),
        "auc": float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else np.nan,
        "base_rate": float(y.mean()),
        "mean_pred": float(p.mean()),
    }


def fit_mu_climatology(train: pd.DataFrame, n_buckets: int = 6
                       ) -> tuple[pd.Series, np.ndarray, float]:
    """Conditional climatology: mean μ per (net-load bucket × hour), on binders.

    The plan's stated backbone, and the thing quantile regression has to beat.
    Bucket edges come from the TRAINING window's net load only — fitting them
    across train+test would leak the scored week's distribution.
    """
    binders = train[train["y_bind"] == 1]
    grand = float(binders["y_mu"].mean()) if len(binders) else 0.0
    if binders.empty:
        return pd.Series(dtype="float64"), np.array([]), grand
    edges = np.unique(np.quantile(train["net_load"].dropna(),
                                  np.linspace(0, 1, n_buckets + 1)[1:-1]))
    cells = binders.groupby([np.digitize(binders["net_load"], edges), binders["hour"]])["y_mu"].mean()
    return cells, edges, grand


def predict_mu_climatology(panel: pd.DataFrame, cells: pd.Series,
                           edges: np.ndarray, grand: float) -> np.ndarray:
    if cells.empty:
        return np.full(len(panel), grand)
    idx = pd.MultiIndex.from_arrays([np.digitize(panel["net_load"], edges), panel["hour"]])
    return cells.reindex(idx).fillna(grand).to_numpy()


def fit_mu_head(train: pd.DataFrame, cols: list[str],
                seed: int = 0) -> HistGradientBoostingRegressor:
    """GBM on log1p(μ), trained on BINDING rows only.

    Training only on binders is what makes this `E[μ | bind]` rather than `E[μ]`.
    And μ is heavy-tailed, so a squared-error fit on the raw scale would spend the
    model on a handful of extreme hours; log1p pulls that in and the prediction is
    mapped back with expm1.
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
