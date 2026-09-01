"""Pure ordering and history-summary policy for Analysis comparisons."""

from __future__ import annotations

import pandas as pd


def joined_top_keys(
    forecast_keys: pd.Index,
    settled_keys: pd.Index,
    *,
    k: int,
    settled_available: bool,
) -> list[str]:
    """Return the visible forecast/DAM comparison ranking.

    DAM leads once it is available, while forecast leaders remain visible as
    comparison rows.  A missed DAM leader must not hide a forecast call.
    """
    forecast_top = [str(key) for key in forecast_keys[:k]]
    if not settled_available:
        return forecast_top
    settled_top = [str(key) for key in settled_keys[:k]]
    settled_set = set(settled_top)
    return settled_top + [key for key in forecast_top if key not in settled_set]


def history_percentiles(
    values: list[float], *, nonzero_only: bool = False, epsilon: float = 0.0
) -> dict[str, float | None]:
    """Return the Brief's five displayed history percentiles.

    Quiet histories are intentionally absent rather than represented as a
    misleading all-zero whisker.  Node callers can pass an epsilon to suppress
    floating-point residue.
    """
    sample = (
        [value for value in values if abs(value) > epsilon]
        if nonzero_only
        else values
    )
    if not sample:
        return {f"p{percentile}": None for percentile in (10, 25, 50, 75, 90)}
    series = pd.Series(sample, dtype=float)
    return {
        f"p{percentile}": float(series.quantile(percentile / 100))
        for percentile in (10, 25, 50, 75, 90)
    }
