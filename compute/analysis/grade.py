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
    # Node-only ranked grade.  The epsilon event mask remains available through
    # the AP/skill fields as a diagnostic, but it is too broad to headline when
    # almost every settlement point has non-zero congestion.
    top_decile_daily_capture: float | None = None
    top_decile_hourly_capture: float | None = None


@dataclass(frozen=True)
class GradeSupport:
    """Evidence displayed beside a grade, never folded into its score."""
    daily_bound_count: int
    hourly_bound_count: int
    forecast_total: float
    settled_total: float


@dataclass(frozen=True)
class GradeResult:
    """Model and persistence outcomes on one identical scoring universe."""
    universe: tuple[str, ...]
    model: GradeMetrics
    persistence: GradeMetrics
    support: GradeSupport | None = None


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


def _top_fraction_capture(predicted: pd.Series, settled: pd.Series,
                          fraction: float) -> float | None:
    """Overlap of equal-size predicted and settled top slices.

    Both sets have ``ceil(fraction × universe)`` members, so this is also
    precision and recall.  Stable sort makes the zero/tie fallback
    deterministic; in the materially-ranked head, values are normally unique.
    """
    if not 0 < fraction <= 1:
        raise ValueError("top fraction must be in (0, 1]")
    if len(predicted) == 0:
        return None
    k = max(1, int(np.ceil(len(predicted) * fraction)))
    forecast_top = set(predicted.sort_values(ascending=False, kind="stable").index[:k])
    settled_top = set(settled.sort_values(ascending=False, kind="stable").index[:k])
    return len(forecast_top & settled_top) / k


def _metrics(predicted: pd.DataFrame, settled: pd.DataFrame,
             settled_bound: pd.DataFrame, *, top_fraction: float | None = None) -> GradeMetrics:
    daily_predicted = predicted.sum(axis=0)
    daily_settled = settled.sum(axis=0)
    daily_bound = settled_bound.any(axis=0)
    daily_ap = expected_average_precision(daily_predicted, daily_bound)
    hourly_ap = expected_average_precision(
        pd.Series(predicted.to_numpy().ravel()), pd.Series(settled_bound.to_numpy().ravel())
    )
    daily_capture = _top_fraction_capture(daily_predicted, daily_settled, top_fraction) if top_fraction else None
    hourly_capture = (
        float(np.mean([
            _top_fraction_capture(predicted.loc[hour], settled.loc[hour], top_fraction)
            for hour in predicted.index
        ]))
        if top_fraction and len(predicted.index) else None
    )
    return GradeMetrics(
        detection_ap=daily_ap,
        magnitude_overlap=_soft_overlap(daily_predicted, daily_settled),
        timing_daily_skill=_chance_adjusted(daily_ap, daily_bound),
        timing_hourly_skill=_chance_adjusted(
            hourly_ap, pd.Series(settled_bound.to_numpy().ravel())
        ),
        top_decile_daily_capture=daily_capture,
        top_decile_hourly_capture=hourly_capture,
    )


def grade_profiles(model: pd.DataFrame, settled: pd.DataFrame, persistence: pd.DataFrame,
                   *, settled_bound: pd.DataFrame | None = None,
                   universe: list[str] | None = None,
                   top_fraction: float | None = None) -> GradeResult:
    """Score model and yesterday-repeated settlement on the same full universe.

    ``settled`` may be sparse: missing values mean no published DAM row, while a
    numeric zero is an explicit settled ``$0``.  Supply ``settled_bound`` when
    the calling query represents that distinction separately; otherwise the
    DataFrame's non-null cells define the ERCOT binding labels.  ``universe``
    extends the forecast/settled/persistence keys with prior-window settled
    vocabulary. Absent values are scored as zero only *after* that universe has
    been formed.
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

    score_universe = list(dict.fromkeys([*(str(key) for key in model.columns),
                                         *(str(key) for key in settled.columns),
                                         *(str(key) for key in persistence.columns),
                                         *(str(key) for key in (universe or []))]))
    model_values = _aligned(model, hours, score_universe)
    settled_values = _aligned(settled, hours, score_universe)
    persistence_values = _aligned(persistence, hours, score_universe)
    labels = settled_bound.reindex(index=hours, columns=score_universe, fill_value=False).fillna(False).astype(bool)
    daily_predicted = model_values.sum(axis=0)
    daily_settled = settled_values.sum(axis=0)
    return GradeResult(
        universe=tuple(score_universe),
        model=_metrics(model_values, settled_values, labels, top_fraction=top_fraction),
        persistence=_metrics(persistence_values, settled_values, labels, top_fraction=top_fraction),
        support=GradeSupport(
            daily_bound_count=int(labels.any(axis=0).sum()),
            hourly_bound_count=int(labels.to_numpy().sum()),
            forecast_total=float(daily_predicted.sum()),
            settled_total=float(daily_settled.sum()),
        ),
    )
