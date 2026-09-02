"""Pure per-delivery-day forecast grade calculations.

Three measures:

1. average precision over daily constraint rankings

2. soft overlap of daily Σμ vectors

3. chance-adjusted average precision over pooled constraint-hours.

The module deliberately has no database or artifact knowledge. Callers pass the
full vocabulary, dense forecast profiles, sparse settled profiles, and the
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
    daily_bound_rate: float
    hourly_bound_rate: float
    forecast_to_settled_ratio: float | None
    magnitude_ceiling: float | None
    magnitude_of_ceiling: float | None


@dataclass(frozen=True)
class GradeResult:
    """Model and persistence outcomes on one identical scoring universe."""

    universe: tuple[str, ...]
    model: GradeMetrics
    persistence: GradeMetrics
    climatology: GradeMetrics | None = None
    support: GradeSupport | None = None


#
# METRICS: actual calculation
#

def expected_average_precision(scores: pd.Series, bound: pd.Series) -> float | None:
    """Rank activity scores against labels with tie-stable average precision.

    Detection supplies daily subject totals; Timing supplies flattened
    subject-hour cells.
    """
    scores, bound = scores.align(bound.astype(bool), join="inner")
    positives = int(bound.sum())
    if positives == 0:
        return None

    frame = pd.DataFrame({"score": scores.astype(float), "bound": bound})
    seen, seen_bound, numerator = 0, 0, 0.0
    for _, group in frame.sort_values("score", ascending=False, kind="stable").groupby(
        "score", sort=False
    ):
        n = len(group)
        p = int(group["bound"].sum())
        if p:
            if n == 1:
                numerator += (seen_bound + 1) / (seen + 1)
            else:
                # For a positive at rank j in a random permutation of this tie,
                # the expected earlier positives are (j - 1) * (p - 1) / (n - 1).
                for j in range(1, n + 1):
                    numerator += (
                        (p / n)
                        * (seen_bound + 1 + (j - 1) * (p - 1) / (n - 1))
                        / (seen + j)
                    )
        seen += n
        seen_bound += p
    return numerator / positives


def _chance_adjusted(ap: float | None, bound: pd.Series) -> float | None:
    """Convert average precision to skill above the settled activity rate."""
    if ap is None:
        return None
    chance = float(bound.mean())
    return None if chance >= 1.0 else (ap - chance) / (1.0 - chance)


def _soft_overlap(predicted: pd.Series, settled: pd.Series) -> float | None:
    """Return the shared fraction of forecast and settled daily congestion mass."""
    denominator = float(predicted.sum() + settled.sum())
    if denominator == 0.0:
        return None
    return float(2.0 * np.minimum(predicted, settled).sum() / denominator)


def _magnitude_support(
    overlap: float | None, forecast_total: float, settled_total: float
) -> tuple[float | None, float | None, float | None]:
    """Calibration ratio, its overlap ceiling, and the share of that ceiling."""
    if settled_total == 0.0:
        return None, None, None
    ratio = forecast_total / settled_total
    ceiling = 2.0 * ratio / (1.0 + ratio) if ratio >= 0.0 else None
    return ratio, ceiling, None if overlap is None or not ceiling else overlap / ceiling


#
# Metrics Support
#
def _aligned(
    values: pd.DataFrame, hours: pd.Index, universe: list[str]
) -> pd.DataFrame:
    """Validate and densify a profile on the shared hours and subject universe."""
    if values.columns.has_duplicates:
        raise ValueError("grade profiles must have unique element keys")
    if not values.index.equals(hours):
        raise ValueError("grade profiles must share an identical delivery-hour index")
    return (
        values.reindex(index=hours, columns=universe, fill_value=0.0)
        .fillna(0.0)
        .astype(float)
    )


def _top_fraction_capture(
    predicted: pd.Series, settled: pd.Series, fraction: float
) -> float | None:
    """Overlap of equal-size predicted and settled top slices."""
    if not 0 < fraction <= 1:
        raise ValueError("top fraction must be in (0, 1]")
    if len(predicted) == 0:
        return None
    k = max(1, int(np.ceil(len(predicted) * fraction)))
    forecast_top = set(predicted.sort_values(ascending=False, kind="stable").index[:k])
    settled_top = set(settled.sort_values(ascending=False, kind="stable").index[:k])
    return len(forecast_top & settled_top) / k


def _metrics(
    predicted: pd.DataFrame,
    settled: pd.DataFrame,
    settled_bound: pd.DataFrame,
    *,
    top_fraction: float | None = None,
) -> GradeMetrics:
    """Calculate daily detection, daily magnitude, and hourly timing metrics."""
    daily_predicted = predicted.sum(axis=0)
    daily_settled = settled.sum(axis=0)
    daily_bound = settled_bound.any(axis=0)
    daily_ap = expected_average_precision(daily_predicted, daily_bound)
    hourly_ap = expected_average_precision(
        pd.Series(predicted.to_numpy().ravel()),
        pd.Series(settled_bound.to_numpy().ravel()),
    )
    daily_capture = (
        _top_fraction_capture(daily_predicted, daily_settled, top_fraction)
        if top_fraction
        else None
    )
    hourly_capture = (
        float(
            np.mean(
                [
                    _top_fraction_capture(
                        predicted.loc[hour], settled.loc[hour], top_fraction
                    )
                    for hour in predicted.index
                ]
            )
        )
        if top_fraction and len(predicted.index)
        else None
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


def grade_profiles(
    model: pd.DataFrame,
    settled: pd.DataFrame,
    persistence: pd.DataFrame,
    *,
    settled_bound: pd.DataFrame | None = None,
    universe: list[str] | None = None,
    climatology: pd.DataFrame | None = None,
    top_fraction: float | None = None,
) -> GradeResult:
    """Score model and yesterday-repeated settlement on the same full universe.

    ``settled`` may be sparse: missing values mean no published DAM row, while a
    numeric zero is an explicit settled ``$0``.
    """
    profiles = (
        (model, settled, persistence)
        if climatology is None
        else (model, settled, persistence, climatology)
    )
    if not all(isinstance(value, pd.DataFrame) for value in profiles):
        raise TypeError(
            "model, settled, persistence, and climatology must be pandas DataFrames"
        )
    hours = model.index
    if not model.index.is_unique:
        raise ValueError("grade profiles must have unique delivery hours")
    if not settled.index.equals(hours) or not persistence.index.equals(hours):
        raise ValueError("grade profiles must share an identical delivery-hour index")
    if climatology is not None and not climatology.index.equals(hours):
        raise ValueError("climatology must share the target delivery-hour index")
    if settled_bound is None:
        settled_bound = settled.notna()
    if not isinstance(settled_bound, pd.DataFrame) or not settled_bound.index.equals(
        hours
    ):
        raise ValueError("settled_bound must share the target delivery-hour index")

    score_universe = list(
        dict.fromkeys(
            [
                *(str(key) for key in model.columns),
                *(str(key) for key in settled.columns),
                *(str(key) for key in persistence.columns),
                *(
                    (str(key) for key in climatology.columns)
                    if climatology is not None
                    else ()
                ),
                *(str(key) for key in (universe or [])),
            ]
        )
    )

    # align profiles to be comparable: have same intervals and "universe" keys
    # (constraints or sps)
    model_values = _aligned(model, hours, score_universe)
    settled_values = _aligned(settled, hours, score_universe)
    persistence_values = _aligned(persistence, hours, score_universe)
    climatology_values = (
        _aligned(climatology, hours, score_universe)
        if climatology is not None
        else None
    )
    labels = (
        settled_bound.reindex(index=hours, columns=score_universe, fill_value=False)
        .fillna(False)
        .astype(bool)
    )

    # GradeSupport helpers
    daily_predicted = model_values.sum(axis=0)
    daily_settled = settled_values.sum(axis=0)
    overlap = _soft_overlap(daily_predicted, daily_settled)
    forecast_total = float(daily_predicted.sum())
    settled_total = float(daily_settled.sum())
    ratio, ceiling, of_ceiling = _magnitude_support(
        overlap, forecast_total, settled_total
    )

    #
    # Metrics: Detection, Magnitude and Timing are packaged in GradeMetrics
    # instance returned by _metrics() - called inline as parameters to
    # GradeResult here for each Source (model, persistence, climatology, etc.)
    #
    return GradeResult(
        universe=tuple(score_universe),
        model=_metrics(model_values, settled_values, labels, top_fraction=top_fraction),
        persistence=_metrics(
            persistence_values, settled_values, labels, top_fraction=top_fraction
        ),
        climatology=(
            None
            if climatology_values is None
            else _metrics(
                climatology_values, settled_values, labels, top_fraction=top_fraction
            )
        ),
        support=GradeSupport(
            daily_bound_count=int(labels.any(axis=0).sum()),
            hourly_bound_count=int(labels.to_numpy().sum()),
            forecast_total=forecast_total,
            settled_total=settled_total,
            daily_bound_rate=float(labels.any(axis=0).mean()),
            hourly_bound_rate=float(labels.to_numpy().mean()),
            forecast_to_settled_ratio=ratio,
            magnitude_ceiling=ceiling,
            magnitude_of_ceiling=of_ceiling,
        ),
    )
