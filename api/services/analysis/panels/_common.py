"""Shared primitives for the Brief panel handlers: tuning constants, the
ranked-handler preamble, the settled-history whisker, and the rank idiom."""

from __future__ import annotations

from datetime import date

import pandas as pd

from api.schemas.analysis import NodeAnalysisUnavailableResponse
from api.services.analysis.resolution import (
    resolve_horizon as _resolve_horizon,
    resolve_run as _resolve_run,
)

NODE_CONGESTION_EPSILON = 1e-6  # $/MWh; suppresses float residue, not economics.
MARKET_PEAK_CT_HOURS = tuple(range(7, 23))  # 7×16, every delivery day.
# Minimum trailing days an element needs before its history yields a trustworthy
# standout baseline.  Unrelated to the top-k row cap — this gates eligibility,
# not row count.
MIN_STANDOUT_HISTORY_DAYS = 10


def _resolve_or_unavailable(
    cur,
    run_id: str | None,
    delivery_date: date,
    horizon: int | None,
    unavailable_cls=NodeAnalysisUnavailableResponse,
):
    """Resolve the run and its served horizon; the shared ranked-handler preamble.

    Returns ``(run_id, horizon, None)`` on success, or ``(run_id, None, soft_fail)``
    when no artifact horizon exists for the day.
    """
    run_id = _resolve_run(cur, run_id)
    horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
    if horizon is None:
        return run_id, None, unavailable_cls(
            available=False,
            unavailable_reason="artifact_missing",
            run_id=run_id,
            delivery_date=delivery_date,
        )
    return run_id, horizon, None


def ranked(series: pd.Series) -> tuple[pd.Series, dict[str, int]]:
    """Descending stable sort plus 1-based ranks keyed by string key.

    The caller pre-filters/abs-es the series; ties keep input order (stable).
    """
    ordered = series.sort_values(ascending=False, kind="stable")
    return ordered, {str(key): rank for rank, key in enumerate(ordered.index, start=1)}


def settled_history_stats(values, *, nonzero_only: bool, gate: bool = True) -> dict:
    """The trailing settled-Σμ whisker: five percentiles plus the raw series.

    ``nonzero_only`` filters to positive days before ranking percentiles (the
    constraint whisker); node whiskers percentile the full signed series.
    ``gate`` nulls the percentiles when the series carries no signal — off only
    for top-nodes, which always reports a numeric whisker.
    """
    series = list(values)
    basis = [value for value in series if value > 0.0] if nonzero_only else series
    if gate:
        empty = not basis if nonzero_only else not any(
            abs(value) > NODE_CONGESTION_EPSILON for value in series
        )
    else:
        empty = False
    quantiles = pd.Series(basis).quantile([0.1, 0.25, 0.5, 0.75, 0.9]) if not empty else None
    return {
        f"settled_history_p{label}": (
            None if empty else float(quantiles.loc[q])
        )
        for label, q in (("10", 0.1), ("25", 0.25), ("50", 0.5), ("75", 0.75), ("90", 0.9))
    } | {"settled_history": series}
