"""Dependency-light point-forecast metrics shared by projection and evaluation."""
from __future__ import annotations

import numpy as np
from scipy.stats import rankdata


def r2(y: np.ndarray, y_hat: np.ndarray) -> float:
    m = np.isfinite(y) & np.isfinite(y_hat)
    y, y_hat = y[m], y_hat[m]
    if y.size < 2:
        return float("nan")
    total = float(((y - y.mean()) ** 2).sum())
    return float("nan") if total <= 0 else 1.0 - float(((y - y_hat) ** 2).sum()) / total


def row_spearman(Y: np.ndarray, Yh: np.ndarray) -> float:
    values = []
    for y, yh in zip(Y, Yh):
        m = np.isfinite(y) & np.isfinite(yh)
        if m.sum() >= 10 and np.ptp(y[m]) and np.ptp(yh[m]):
            values.append(np.corrcoef(rankdata(y[m]), rankdata(yh[m]))[0, 1])
    return float(np.mean(values)) if values else float("nan")


def sign_agreement(Y: np.ndarray, Yh: np.ndarray, deadband: float = 1.0) -> float:
    m = np.isfinite(Y) & np.isfinite(Yh) & (np.abs(Y) > deadband)
    return float((np.sign(Y[m]) == np.sign(Yh[m])).mean()) if m.any() else float("nan")


def topdecile_hit(Y: np.ndarray, Yh: np.ndarray) -> float:
    values = []
    for y, yh in zip(Y, Yh):
        m = np.isfinite(y) & np.isfinite(yh)
        n = int(m.sum())
        if n >= 20:
            k = max(1, n // 10)
            values.append(len(set(np.argsort(-y[m])[:k]) & set(np.argsort(-yh[m])[:k])) / k)
    return float(np.mean(values)) if values else float("nan")


def score_matrix(Y: np.ndarray, Yh: np.ndarray) -> dict:
    """Point-forecast accuracy and screening metrics; flat ranking is undefined."""
    keep = np.ptp(Yh, axis=1) != 0
    return {
        "pooled_r2": r2(Y.ravel(), Yh.ravel()),
        "mae": float(np.nanmean(np.abs(Y - Yh))),
        "rank_spearman": row_spearman(Y, Yh),
        "sign_agree": sign_agreement(Y, Yh),
        "topdecile_hit": topdecile_hit(Y[keep], Yh[keep]) if keep.any() else float("nan"),
    }

