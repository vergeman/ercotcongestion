"""Pure per-delivery-day forecast grade calculations.

Three measures:

average precision over daily constraint rankings, soft overlap of daily Σμ
vectors, and chance-adjusted average precision over pooled constraint-hours.
The module deliberately has no database or artifact knowledge.  Callers pass
the full vocabulary, dense forecast profiles, sparse settled profiles, and the
settled-row labels that distinguish a published ``$0`` from no DAM row.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GradeMetrics:
    """The prototype's three independently displayed grade values."""
    detection_ap: float | None
    magnitude_overlap: float | None
    timing_daily_skill: float | None
    timing_hourly_skill: float | None


@dataclass(frozen=True)
class GradeResult:
    """Model and persistence outcomes on one identical scoring universe."""
    universe: tuple[str, ...]
    model: GradeMetrics
    persistence: GradeMetrics


def expected_average_precision(scores: pd.Series, bound: pd.Series) -> float | None:
    """Average precision with expected precision inside equal-score ties.

    The large zero-forecast tie cannot be ordered arbitrarily: doing so makes
    the grade depend on constraint-key spelling.  This is the expectation over
    a random permutation of every equal-score group, as specified in the v6
    prototype.
    """
    scores, bound = scores.align(bound.astype(bool), join="inner")
    positives = int(bound.sum())
    if positives == 0:
        return None

    frame = pd.DataFrame({"score": scores.astype(float), "bound": bound})
    seen, seen_bound, numerator = 0, 0, 0.0
    for _, group in frame.sort_values("score", ascending=False, kind="stable").groupby("score", sort=False):
        n = len(group)
        p = int(group["bound"].sum())
        if p:
            if n == 1:
                numerator += (seen_bound + 1) / (seen + 1)
            else:
                # For a positive at rank j in a random permutation of this tie,
                # the expected earlier positives are (j - 1) * (p - 1) / (n - 1).
                for j in range(1, n + 1):
                    numerator += (p / n) * (
                        seen_bound + 1 + (j - 1) * (p - 1) / (n - 1)
                    ) / (seen + j)
        seen += n
        seen_bound += p
    return numerator / positives


def _chance_adjusted(ap: float | None, bound: pd.Series) -> float | None:
    if ap is None:
        return None
    chance = float(bound.mean())
    return None if chance >= 1.0 else (ap - chance) / (1.0 - chance)


def _soft_overlap(predicted: pd.Series, settled: pd.Series) -> float | None:
    denominator = float(predicted.sum() + settled.sum())
    if denominator == 0.0:
        return None
    return float(2.0 * np.minimum(predicted, settled).sum() / denominator)


def _aligned(values: pd.DataFrame, hours: pd.Index, universe: list[str]) -> pd.DataFrame:
    if values.columns.has_duplicates:
        raise ValueError("grade profiles must have unique element keys")
    if not values.index.equals(hours):
        raise ValueError("grade profiles must share an identical delivery-hour index")
    return values.reindex(index=hours, columns=universe, fill_value=0.0).fillna(0.0).astype(float)


def _metrics(predicted: pd.DataFrame, settled: pd.DataFrame,
             settled_bound: pd.DataFrame) -> GradeMetrics:
    daily_predicted = predicted.sum(axis=0)
    daily_settled = settled.sum(axis=0)
    daily_bound = settled_bound.any(axis=0)
    daily_ap = expected_average_precision(daily_predicted, daily_bound)
    hourly_ap = expected_average_precision(
        pd.Series(predicted.to_numpy().ravel()), pd.Series(settled_bound.to_numpy().ravel())
    )
    return GradeMetrics(
        detection_ap=daily_ap,
        magnitude_overlap=_soft_overlap(daily_predicted, daily_settled),
        timing_daily_skill=_chance_adjusted(daily_ap, daily_bound),
        timing_hourly_skill=_chance_adjusted(
            hourly_ap, pd.Series(settled_bound.to_numpy().ravel())
        ),
    )


def grade_profiles(model: pd.DataFrame, settled: pd.DataFrame, persistence: pd.DataFrame,
                   *, settled_bound: pd.DataFrame | None = None) -> GradeResult:
    """Score model and yesterday-repeated settlement on the same full universe.

    ``settled`` may be sparse: missing values mean no published DAM row, while a
    numeric zero is an explicit settled ``$0``.  Supply ``settled_bound`` when
    the calling query represents that distinction separately; otherwise the
    DataFrame's non-null cells define the ERCOT binding labels.  The universe is
    every key in the forecast vocabulary, settlement, or persistence — absent
    values are scored as zero only *after* that universe has been formed.
    """
    if not all(isinstance(value, pd.DataFrame) for value in (model, settled, persistence)):
        raise TypeError("model, settled, and persistence must be pandas DataFrames")
    hours = model.index
    if not model.index.is_unique:
        raise ValueError("grade profiles must have unique delivery hours")
    if not settled.index.equals(hours) or not persistence.index.equals(hours):
        raise ValueError("grade profiles must share an identical delivery-hour index")
    if settled_bound is None:
        settled_bound = settled.notna()
    if not isinstance(settled_bound, pd.DataFrame) or not settled_bound.index.equals(hours):
        raise ValueError("settled_bound must share the target delivery-hour index")

    universe = list(dict.fromkeys([*(str(key) for key in model.columns),
                                   *(str(key) for key in settled.columns),
                                   *(str(key) for key in persistence.columns)]))
    model_values = _aligned(model, hours, universe)
    settled_values = _aligned(settled, hours, universe)
    persistence_values = _aligned(persistence, hours, universe)
    labels = settled_bound.reindex(index=hours, columns=universe, fill_value=False).fillna(False).astype(bool)
    return GradeResult(
        universe=tuple(universe),
        model=_metrics(model_values, settled_values, labels),
        persistence=_metrics(persistence_values, settled_values, labels),
    )
