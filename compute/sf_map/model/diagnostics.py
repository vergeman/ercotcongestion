"""Per-refit-window fit diagnostics.

Emitted per refit window (under ``runs/<run_id>/sf/``) so a reviewer can tell at
a glance whether the fit on any given week is trustworthy: R² on the fit rows,
per-SP R², the kept-constraint list with binding-hour counts, and the
constraints dropped below ``--min-binding-hours``.

"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


def _r2(y: np.ndarray, y_hat: np.ndarray) -> float:
    """Coefficient of determination over finite pairs.

    R² measures how much of the variation in the actual congestion prices the
    shift-factor model explains:

    R^2 = 1 − (model squared error / baseline squared error)
    R^2:
      1: predictions match actual congestion perfectly.
      0: no improvement over predicting the average congestion.
    < 0: worse than predicting the average.
    0.75: the model explains about 75% of the observed variation, under this
    squared-error comparison.

    """
    mask = np.isfinite(y) & np.isfinite(y_hat)
    if mask.sum() < 2:
        return float("nan")
    y = y[mask]
    y_hat = y_hat[mask]
    ss_res = float(((y - y_hat) ** 2).sum())    # model squared error
    ss_tot = float(((y - y.mean()) ** 2).sum()) # baseline squared error
    if ss_tot <= 0.0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def refit_diagnostics(
    M_window: pd.DataFrame,
    C_window: pd.DataFrame,
    SF: pd.DataFrame,
    min_hours: int,
) -> dict[str, Any]:
    """Compute per-refit-window diagnostics.

    ``kept_mask``: those that bind gte to min_hours

    ``kept_constraints`` reports the surviving fit columns with their binding
    hour counts. Anything in ``M_window`` that was filtered out lands in
    ``dropped_constraints``.

    """
    binding_counts = (M_window > 0).sum()
    kept_mask = binding_counts >= min_hours
    kept_names = binding_counts[kept_mask].sort_values(ascending=False)
    dropped_names = binding_counts[~kept_mask].sort_values(ascending=False)

    kept = [
        {"key": str(name), "binding_hours": int(n)}
        for name, n in kept_names.items()
    ]
    dropped = [
        {"key": str(name), "binding_hours": int(n)}
        for name, n in dropped_names.items()
    ]

    # Prediction: C_hat = -M · SFᵀ, restricted to fitted rows / kept cols.
    r2_overall = float("nan")

    per_sp_r2: dict[str, float] = {}
    if not SF.empty and not M_window.empty:

        common_cols = M_window.columns.intersection(SF.index)  # cols: common constraints
        idx = M_window.index.intersection(C_window.index)      # rows: common hours

        if len(common_cols) > 0 and len(idx) > 0:

            X = M_window.loc[idx, common_cols].to_numpy(dtype=float)  # hrs x constraints

            SFv = SF.loc[common_cols].to_numpy(dtype=float)          # SF: (constraints x SPs)

            Y_hat = -(X @ SFv)                                       # (hours × SPs)

            Y = C_window.loc[idx, SF.columns].to_numpy(dtype=float)  # Y =  C: (hrs x SP)

            # .ravel() flattens a N-D numpy array into a 1-d array
            # r^2 correlation (0, 1) between actual (Y) and predicted (Y_hat)
            # overall: single number
            r2_overall = _r2(Y.ravel(), Y_hat.ravel())

            # for each SP, calculate the R^2
            for j, sp in enumerate(SF.columns):
                per_sp_r2[str(sp)] = _r2(Y[:, j], Y_hat[:, j])

    return {
        "n_fit_hours": int(M_window.shape[0]),
        "n_constraints_in_window": int(M_window.shape[1]),
        "n_kept": int(len(kept)),
        "n_dropped": int(len(dropped)),
        "n_sf_clipped": int(SF.attrs.get("n_clipped", 0)),
        "min_binding_hours": int(min_hours),
        "r2_overall": None if np.isnan(r2_overall) else r2_overall,
        "per_sp_r2": {
            sp: (None if np.isnan(v) else v) for sp, v in per_sp_r2.items()
        },
        "kept_constraints": kept,
        "dropped_constraints": dropped,
    }


def diagnostics_filename(window_start: datetime) -> str:
    """Stable filename for the per-window diagnostics JSON."""
    return f"diagnostics_{window_start.strftime('%Y%m%d')}.json"
