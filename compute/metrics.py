"""Dependency-light screening metrics shared by forecast paths."""
from __future__ import annotations

import numpy as np
from scipy.stats import rankdata


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


def screening_metrics(Y: np.ndarray, Yh: np.ndarray) -> dict:
    """Screening metrics; flat predictions have no top-decile ranking."""
    keep = np.ptp(Yh, axis=1) != 0
    return {
        "rank_spearman": row_spearman(Y, Yh),
        "sign_agree": sign_agreement(Y, Yh),
        "topdecile_hit": topdecile_hit(Y[keep], Yh[keep]) if keep.any() else float("nan"),
    }
