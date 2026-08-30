"""Schemas served by the Scoreboard summary."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel
from schemas.common import BootstrapSectionStatus

# ---- /scoreboard/summary headline ----------------------------------------
#
# The backtest scoreboard's rolling headline (plan/0102 §0001, spec-phase3
# §3/§6). Rolling 30/90-day tiles read from ``scoreboard_weekly`` — the thin
# panel view, not the full board (that is 0002). The one non-negotiable: a
# model figure never ships alone. Every currency carries its ``persistence``
# delta and the ``oracle`` ceiling (and ``climatology`` for context), so the
# client cannot render a lone model number (§6 integrity rule).


class HeadlineCurrency(BaseModel):
    """One pre-registered currency in one rolling window, model + its comparators.

    ``model`` never travels without ``persistence``/``climatology``/``oracle`` —
    the integrity rule (spec §6). ``persistence_delta = model - persistence`` is
    the raw delta; read its sign against ``higher_is_better`` (all current
    currencies are higher-is-better, so a positive delta means the model beats
    persistence). ``oracle`` is the ceiling the model is measured against. Any
    value can be ``None`` when a source had no scored week in the window.
    """
    currency: str            # topdecile_hit | rank_spearman | sign_agree
    higher_is_better: bool
    model: float | None = None
    persistence: float | None = None
    climatology: float | None = None
    oracle: float | None = None
    persistence_delta: float | None = None   # model - persistence (raw, sign per flag)


class HeadlineWindow(BaseModel):
    """One rolling window (30d / 90d) — every currency pooled over the trailing
    weeks. ``weeks`` is how many weekly rows fed the pool; ``week_start``/
    ``week_end`` bound them. The pool is an ``n_hours``-weighted mean of the weekly
    cells — an approximation of the fully pooled stat, which lives on the full
    board (0002).
    """
    window_days: int         # 30 | 90
    weeks: int
    week_start: date
    week_end: date
    currencies: list[HeadlineCurrency]


class ScoreboardHeadline(BaseModel):
    """The rolling headline for one board (``run_id``).

    ``run_id`` is the model version whose backtest this is; ``as_of_week`` is the
    latest week on the board (the anchor the rolling windows trail from).
    """
    run_id: str
    as_of_week: date
    windows: list[HeadlineWindow]


# ---- /scoreboard/summary weekly ------------------------------------------
#
# The full weekly backtest series (plan/0102 §0002, spec-phase3 §3/§5/§7) — the
# data behind the scoreboard *page* the panel's "View full scoreboard" link
# targets. Every response carries all sources (model + baselines + oracle) so a
# lone model figure can't be rendered (§6), plus a pooled pre/post-RTC+B summary
# with pooled screening summaries.


class WeeklyPoint(BaseModel):
    """One ``scoreboard_weekly`` row served for the chart — one (week, source).

    Screening currencies (``rank_spearman``/``sign_agree``/``topdecile_hit``) lead
    the page. All nullable — a NULL cell
    (e.g. the flat ``null`` source's declined top-decile) rides through as ``None``.
    """
    week: date
    source: str
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class SourcePooled(BaseModel):
    """One source's pooled currencies over a split — the week-mean of each metric
    ``None`` when the source had no scored week."""
    source: str
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None


class WeeklySplit(BaseModel):
    """A pooled slice — ``all`` / ``pre_rtc_b`` / ``post_rtc_b`` — so the RTC+B
    structural break is visible on every pooled stat (§5): pooled must not launder
    the post-cutover number. ``beats_persistence`` is the existence test (model > persistence on all three
    screening currencies). ``sources`` always includes model + persistence +
    climatology + oracle (§6)."""
    label: str            # all | pre_rtc_b | post_rtc_b
    n_weeks: int
    sources: list[SourcePooled]
    beats_persistence: bool | None = None


class ScoreboardWeekly(BaseModel):
    """The weekly series + pooled summary for one board.

    ``primary_source`` echoes the requested ``source`` (the series the page
    foregrounds); the comparators ride along in ``points`` regardless, so the
    client can never render a lone model figure. ``rtc_b_cutover`` is the split
    date the ``pre_``/``post_rtc_b`` summaries divide on.
    """
    run_id: str
    primary_source: str
    rtc_b_cutover: date
    points: list[WeeklyPoint]
    splits: list[WeeklySplit]


# ---- /scoreboard/summary daily section -----------------------------------
#
# The LIVE scoreboard (plan/0102 §0003, spec-phase3 §3) — per-delivery-day grades
# of the SERVED forecast, scored against realized once DAM publishes, the live
# counterpart to the weekly backtest board. Same integrity rule (§6): every
# response carries all sources (model + persistence + climatology + oracle + the
# ``null`` flat tripwire), so a lone model figure can't be rendered. Same
# ``score_matrix`` currency as the weekly board, so a live number and a backtest
# number are directly comparable. (Miss-attribution — /scoreboard/miss — is
# deferred out of 0003; the per-day grade is the shipped live surface.)


class DailyPoint(BaseModel):
    """One ``scoreboard_daily`` row — one (delivery_date, source) live grade.

    Same point-metric currency columns as ``WeeklyPoint``. ``model_coverage`` is NULL for
    now (it needs the prediction-time key set, the deferred snapshot); ``sf_coverage``
    rides along so a collapse day reads as a coverage gap, not lost skill. All
    nullable — a declined/flat cell (e.g. the ``null`` source's screening) is ``None``.

    ``horizon`` names the forecast track the row grades (1 = final, 2 = preview).
    It rides on every point because the board carries one horizon at a time and a
    reader must never have to guess which one it is looking at.
    """
    delivery_date: date
    source: str
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

    ``run_id`` is the model version being graded live (the same version the forecast
    served). ``primary_source`` identifies the model series the page foregrounds;
    every source rides along in ``points`` regardless, so the client
    can never render a lone model figure. ``selected_delivery_date`` and
    ``horizon`` make the selected final forecast explicit.
    """
    run_id: str
    primary_source: str
    horizon: int
    selected_delivery_date: date
    points: list[DailyPoint]


# ---- /scoreboard/summary history -----------------------------------------

class ScoreHistoryPoint(BaseModel):
    """One chart point from the weekly backtest or a served final grade."""
    source: str
    cadence: Literal["backtest_weekly", "served_daily"]
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
    """Weekly walk-forward history followed by final served-day grades."""
    primary_source: str
    weekly_run_id: str
    daily_run_id: str | None = None
    boundary_date: date | None = None
    points: list[ScoreHistoryPoint]



class ScoreboardSummaryResponse(BaseModel):
    """One bundled payload for the Scoreboard page summary (0137).

    ``weekly``/``headline`` read ``scoreboard_weekly``; ``daily`` is the latest
    final served grade and the final served tail of ``history`` resolves
    independently from ``scoreboard_daily``.
    A field is ``null`` exactly when its source section would 503.
    """
    weekly: ScoreboardWeekly | None
    headline: ScoreboardHeadline | None
    daily: ScoreboardDaily | None
    history: ScoreboardHistory | None
    availability: dict[str, BootstrapSectionStatus]
