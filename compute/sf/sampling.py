"""Monte Carlo sampling and score calculations for SF projection."""
from __future__ import annotations

import numpy as np
import pandas as pd

from compute.mu.score import score_matrix

N_DRAWS = 200
DRAW_CHUNK = 25
RESID_CAP = 500_000
QUANTILES = (10, 50, 90)


def residual_pool(prior: pd.DataFrame, cap: int = RESID_CAP,
                  rng: np.random.Generator | None = None) -> np.ndarray:
    """Return prior out-of-sample log-space errors for the conditional μ head."""
    b = prior[(prior["y_bind"] == 1) & prior["y_mu"].notna()]
    if b.empty:
        return np.array([], dtype=np.float32)
    eps = (np.log1p(b["y_mu"].to_numpy(np.float64))
           - np.log1p(np.clip(b["mu_gbm"].to_numpy(np.float64), 0, None)))
    eps = eps[np.isfinite(eps)].astype(np.float32)
    if len(eps) > cap:
        rng = rng or np.random.default_rng(0)
        eps = rng.choice(eps, size=cap, replace=False)
    return eps


def _wide(week_preds: pd.DataFrame, col: str, hours: pd.DatetimeIndex,
          cols: pd.Index) -> np.ndarray:
    w = week_preds.pivot_table(index="interval_ts", columns="key", values=col,
                               aggfunc="mean")
    return w.reindex(index=hours, columns=cols).fillna(0.0).to_numpy(np.float32)


def draw_congestion(week_preds: pd.DataFrame, SF: pd.DataFrame,
                    hours: pd.DatetimeIndex, eps: np.ndarray,
                    n_draws: int = N_DRAWS,
                    rng: np.random.Generator | None = None, *, want_point: bool = False,
                    ) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Draw sampled nodal congestion, optionally returning its deterministic mean."""
    rng = rng or np.random.default_rng(0)
    cols = SF.index
    P = _wide(week_preds, "p_bind", hours, cols)
    MU = _wide(week_preds, "mu_gbm", hours, cols)
    SFm = SF.to_numpy(np.float32)
    H, K, N = len(hours), len(cols), SF.shape[1]
    out = np.empty((n_draws, H, N), dtype=np.float32)
    log_mu = np.log1p(np.clip(MU, 0, None))
    for lo in range(0, n_draws, DRAW_CHUNK):
        d = min(DRAW_CHUNK, n_draws - lo)
        bind = rng.random((d, H, K), dtype=np.float32) < P
        e = (rng.choice(eps, size=(d, H, K)) if len(eps)
             else np.zeros((d, H, K), np.float32))
        mu = np.expm1(log_mu[None] + e) * bind
        np.clip(mu, 0, None, out=mu)
        out[lo:lo + d] = -(mu.reshape(d * H, K) @ SFm).reshape(d, H, N)
    if want_point:
        return out, -(P * MU @ SFm).astype(np.float32)
    return out


def band_metrics(Y: np.ndarray, p10: np.ndarray, p50: np.ndarray,
                 p90: np.ndarray) -> dict:
    """Calculate coverage-first band metrics using the served percentile arrays."""
    inside = (Y >= p10) & (Y <= p90)
    return {"coverage80": float(np.nanmean(inside)),
            "band_width": float(np.nanmean(p90 - p10)),
            "pinball": float(np.nanmean([_pinball(Y, q, p / 100)
                                           for q, p in zip((p10, p50, p90), QUANTILES)])),
            **score_matrix(Y, p50)}


def _pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    d = y - q
    return float(np.nanmean(np.maximum(tau * d, (tau - 1) * d)))
