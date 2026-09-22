"""Schemas served by the Scoreboard summary."""

from datetime import date
from pydantic import BaseModel, Field
from api.schemas.common import BootstrapSectionStatus, SourceDescriptor

# ---- /scoreboard/summary weekly ------------------------------------------
#
# The full weekly backtest series plus independently hours-weighted pools. All
# spans all time; pre-RTC+B is backtest-only and post-RTC+B includes live days.


class WeeklyPoint(BaseModel):
    """One ``scoreboard_weekly`` row served for the chart — one (week, source).

    Screening metrics (``rank_spearman``/``sign_agree``/``topdecile_hit``) lead
    the page. All nullable — a NULL cell (e.g. the flat ``null`` source's
    declined top-decile) rides through as ``None``.

    """

    week: date
    source_id: str
    series_id: str
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class SourcePooled(BaseModel):
    """One source's hours-weighted metrics over a split, or ``None`` if unscored."""

    source_id: str
    series_id: str
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None


class WeeklySplit(BaseModel):
    """A pooled slice — ``all`` / ``pre_rtc_b`` / ``post_rtc_b`` — so the RTC+B
    structural break is visible on every pooled stat.

    ``beats_persistence`` is the existence test (model > persistence on all
    three screening currencies).

    ``sources`` always includes model + persistence + climatology + oracle

    """

    label: str  # all | pre_rtc_b | post_rtc_b
    n_weeks: int
    n_days: int
    sources: list[SourcePooled]
    beats_persistence: bool | None = None


class ScoreboardWeekly(BaseModel):
    """The weekly series + pooled summary for one board.

    ``primary_source`` echoes the requested ``source`` (the series the page
    foregrounds) ``rtc_b_cutover`` is the split date the
    ``pre_``/``post_rtc_b`` summaries divide on.

    """

    run_id: str
    primary_source_id: str
    rtc_b_cutover: date
    points: list[WeeklyPoint]
    splits: list[WeeklySplit]
    sources: list[SourceDescriptor] = Field(default_factory=list)


# ---- /scoreboard/summary daily section -----------------------------------
#
# The LIVE scoreboard. per-delivery-day grades of the SERVED forecast, scored
# against realized once DAM publishes, the live counterpart to the weekly
# backtest board.
#

class DailyPoint(BaseModel):
    """One ``scoreboard_daily`` row — one (delivery_date, source) live grade.

    """

    delivery_date: date
    source_id: str
    series_id: str
    horizon: int
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class ScoreboardDaily(BaseModel):
    """The newest final live grade for one run.

    ``run_id`` is the model version being graded live (the same version the
    forecast served).

    ``primary_source`` identifies the model series the page foregrounds; every
    source rides along in ``points`` regardless, so the client can never render
    a lone model figure.

    ``selected_delivery_date`` and ``horizon`` make the selected final forecast
    explicit.

    """

    run_id: str
    primary_source_id: str
    horizon: int
    selected_delivery_date: date
    points: list[DailyPoint]
    sources: list[SourceDescriptor] = Field(default_factory=list)


# ---- /scoreboard/summary history -----------------------------------------


class ScoreHistoryPoint(BaseModel):
    """One chart point from either separately returned Scoreboard cadence."""

    source_id: str
    series_id: str
    week: date | None = None
    delivery_date: date | None = None
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class ScoreboardHistory(BaseModel):
    """Distinct weekly walk-forward and final served-day chart histories."""

    primary_source_id: str
    weekly_run_id: str
    daily_run_id: str | None = None
    weekly_points: list[ScoreHistoryPoint]
    served_daily_points: list[ScoreHistoryPoint] = Field(default_factory=list)
    sources: list[SourceDescriptor] = Field(default_factory=list)


class ScoreboardSummaryResponse(BaseModel):
    """One bundled payload for the Scoreboard page summary.

    ``weekly`` reads ``scoreboard_weekly``; ``daily`` is the latest final served
    grade and the final served tail of ``history`` resolves independently from
    ``scoreboard_daily``.

    A field is ``null`` exactly when its source section would 503.

    """

    weekly: ScoreboardWeekly | None
    daily: ScoreboardDaily | None
    history: ScoreboardHistory | None
    availability: dict[str, BootstrapSectionStatus]
