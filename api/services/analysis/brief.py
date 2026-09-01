"""Composition service for the Analysis Brief endpoints."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import logging
from threading import Lock
from time import perf_counter
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg.rows import dict_row

from api.services.analysis import panels
from api.db import get_pool
from api.schemas.analysis import (
    BriefDayResponse,
    BriefDetailsResponse,
    BriefHeroShellResponse,
    BriefHeroStatsResponse,
)

logger = logging.getLogger(__name__)
_CT = ZoneInfo("America/Chicago")
_BRIEF_SLOW_REQUEST_SECONDS = 1.0

# A settled delivery day's Brief is immutable: a past day's final artifact and
# its day-ahead DAM inputs no longer change, so the whole composed payload —
# decode and all the section pandas can be memoized. Payloads are small JSON,
# so this is bounded by count, not bytes. Keyed by (run_id, day, horizon).
_BRIEF_CACHE_MAX = 512
_BRIEF_CACHE: "OrderedDict[tuple[str, date, int], BriefDayResponse]" = OrderedDict()
_BRIEF_HERO_CACHE: "OrderedDict[tuple[str, date, int], BriefHeroShellResponse]" = (
    OrderedDict()
)
_BRIEF_HERO_STATS_CACHE: (
    "OrderedDict[tuple[str, date, int], BriefHeroStatsResponse]"
) = OrderedDict()
_BRIEF_DETAILS_CACHE: "OrderedDict[tuple[str, date, int], BriefDetailsResponse]" = (
    OrderedDict()
)
_BRIEF_CACHE_LOCK = Lock()


def _brief_cache_get(key: tuple[str, date, int]) -> "BriefDayResponse | None":
    with _BRIEF_CACHE_LOCK:
        response = _BRIEF_CACHE.get(key)
        if response is not None:
            _BRIEF_CACHE.move_to_end(key)
        return response


def _brief_cache_put(key: tuple[str, date, int], response: "BriefDayResponse") -> None:
    with _BRIEF_CACHE_LOCK:
        _BRIEF_CACHE[key] = response
        _BRIEF_CACHE.move_to_end(key)
        while len(_BRIEF_CACHE) > _BRIEF_CACHE_MAX:
            _BRIEF_CACHE.popitem(last=False)


def _brief_section_cache_get(cache: OrderedDict, key: tuple[str, date, int]):
    with _BRIEF_CACHE_LOCK:
        response = cache.get(key)
        if response is not None:
            cache.move_to_end(key)
        return response


def _brief_section_cache_put(
    cache: OrderedDict, key: tuple[str, date, int], response
) -> None:
    with _BRIEF_CACHE_LOCK:
        cache[key] = response
        cache.move_to_end(key)
        while len(cache) > _BRIEF_CACHE_MAX:
            cache.popitem(last=False)


def _brief_is_final(cur, delivery_date: date, horizon: int) -> bool:
    """A day whose Brief can no longer change. The Brief reads only day-ahead
    DAM data (shadow prices, SPP) — published before the delivery day and never
    revised — so it is fixed once (a) the final artifact has landed
    (``horizon == 1``, not a preview), (b) the day is strictly past in CT, so its
    DAM is fully ingested (no partial-ingestion race), and (c) that DAM is
    actually present (guards a stalled feed). Today/preview days recompute."""
    if horizon != 1 or delivery_date >= datetime.now(_CT).date():
        return False
    return panels._dam_landed(cur, delivery_date)


def _timed_brief_section(name: str, handler, *args):
    """Run one composed section and retain its wall time for slow-request logs."""
    started = perf_counter()
    return name, handler(*args), perf_counter() - started


def _brief_neighbor_dates(
    cur, run_id: str, delivery_date: date
) -> tuple[date | None, date | None]:
    """The nearest artifact-backed days for Brief's date controls.

    This replaces full neighbouring Brief prefetches: the controls need only
    know whether a day can be selected, not its expensive panel payload.
    """
    cur.execute(
        "SELECT delivery_date FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date < %s "
        "ORDER BY delivery_date DESC, horizon ASC LIMIT 1",
        (run_id, delivery_date),
    )
    previous = cur.fetchone()
    cur.execute(
        "SELECT delivery_date FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date > %s "
        "ORDER BY delivery_date ASC, horizon ASC LIMIT 1",
        (run_id, delivery_date),
    )
    following = cur.fetchone()
    return (
        None if previous is None else previous["delivery_date"],
        None if following is None else following["delivery_date"],
    )


def _compose_brief_details(
    day: date, run_id: str, horizon: int | None, *, include_standouts: bool = True
) -> BriefDetailsResponse:
    """Compose secondary panels without delaying the hero shell."""
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=6) as pool:
        sections = {
            "context": pool.submit(
                _timed_brief_section,
                "context",
                panels.get_context,
                day,
                run_id,
                horizon,
                14,
            ),
            "top_nodes": pool.submit(
                _timed_brief_section,
                "top_nodes",
                panels.get_top_nodes,
                day,
                run_id,
                horizon,
                10,
            ),
            "top_constraints": pool.submit(
                _timed_brief_section,
                "top_constraints",
                panels.get_top_constraints,
                day,
                run_id,
                horizon,
                10,
            ),
            "grade": pool.submit(
                _timed_brief_section, "grade", panels.get_grade, day, run_id, horizon
            ),
            "grade_history": pool.submit(
                _timed_brief_section,
                "grade_history",
                panels.get_grade_history,
                day,
                run_id,
                horizon,
                30,
            ),
        }
        if include_standouts:
            sections["standouts"] = pool.submit(
                _timed_brief_section,
                "standouts",
                panels.get_standouts,
                day,
                run_id,
                horizon,
                4,
            )
        completed = {name: future.result() for name, future in sections.items()}
    response = BriefDetailsResponse(
        context=completed["context"][1],
        standouts=completed["standouts"][1] if include_standouts else None,
        top_nodes=completed["top_nodes"][1],
        top_constraints=completed["top_constraints"][1],
        grade=completed["grade"][1],
        grade_history=completed["grade_history"][1],
    )
    elapsed = perf_counter() - started
    if elapsed >= _BRIEF_SLOW_REQUEST_SECONDS:
        timings = ", ".join(
            f"{name}={result[2]:.3f}s" for name, result in completed.items()
        )
        logger.info(
            "brief_details_profile day=%s run=%s horizon=%s total=%.3fs %s",
            day,
            run_id,
            horizon,
            elapsed,
            timings,
        )
    return response


def hero_shell(
    delivery_date: date | None, run_id: str | None, day: date | None = None
) -> BriefHeroShellResponse:
    """Serve the Brief prose and map before its slower stat-card evidence."""
    delivery_date = panels._resolve_brief_delivery_date(delivery_date, day)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = panels._resolve_run(cur, run_id)
        horizon = panels._resolve_horizon(cur, run_id, delivery_date, None)
        if (
            horizon is not None
            and horizon == 1
            and delivery_date < datetime.now(_CT).date()
        ):
            cached = _brief_section_cache_get(
                _BRIEF_HERO_CACHE, (run_id, delivery_date, horizon)
            )
            if cached is not None:
                return cached
        previous, following = _brief_neighbor_dates(cur, run_id, delivery_date)
    hero = panels.get_hero(delivery_date, run_id, horizon, include_condition=False)
    response = BriefHeroShellResponse(
        hero=hero,
        previous_delivery_date=previous,
        next_delivery_date=following,
    )
    if (
        horizon is not None
        and horizon == 1
        and delivery_date < datetime.now(_CT).date()
        and response.hero.available
        and response.hero.provenance.basis == "settled"
    ):
        _brief_section_cache_put(
            _BRIEF_HERO_CACHE, (run_id, delivery_date, horizon), response
        )
    return response


def hero_stats(
    delivery_date: date | None, run_id: str | None, day: date | None = None
) -> BriefHeroStatsResponse:
    """Load every hero stat card in one response after prose and map paint."""
    delivery_date = panels._resolve_brief_delivery_date(delivery_date, day)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = panels._resolve_run(cur, run_id)
        horizon = panels._resolve_horizon(cur, run_id, delivery_date, None)
        if horizon is None:
            raise HTTPException(status_code=404, detail="artifact_missing")
        cache_key = (run_id, delivery_date, horizon)
        if horizon == 1 and delivery_date < datetime.now(_CT).date():
            cached = _brief_section_cache_get(_BRIEF_HERO_STATS_CACHE, cache_key)
            if cached is not None:
                return cached
    hero = panels.get_hero(delivery_date, run_id, horizon)
    if not hero["available"]:
        raise HTTPException(status_code=404, detail="artifact_missing")
    response = BriefHeroStatsResponse(
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        slots=hero["slots"],
    )
    if (
        horizon == 1
        and delivery_date < datetime.now(_CT).date()
        and hero["provenance"]["basis"] == "settled"
    ):
        _brief_section_cache_put(_BRIEF_HERO_STATS_CACHE, cache_key, response)
    return response


def details(
    delivery_date: date | None,
    run_id: str | None,
    include_standouts: bool = True,
    day: date | None = None,
) -> BriefDetailsResponse:
    """Compose non-hero Brief panels after the reader can see the day’s story."""
    delivery_date = panels._resolve_brief_delivery_date(delivery_date, day)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = panels._resolve_run(cur, run_id)
        horizon = panels._resolve_horizon(cur, run_id, delivery_date, None)
        cache_key = None if horizon is None else (run_id, delivery_date, horizon)
        if (
            include_standouts
            and cache_key is not None
            and horizon == 1
            and delivery_date < datetime.now(_CT).date()
        ):
            cached = _brief_section_cache_get(_BRIEF_DETAILS_CACHE, cache_key)
            if cached is not None:
                return cached
        final = horizon is not None and _brief_is_final(cur, delivery_date, horizon)
    response = _compose_brief_details(
        delivery_date, run_id, horizon, include_standouts=include_standouts
    )
    if include_standouts and final and cache_key is not None:
        _brief_section_cache_put(_BRIEF_DETAILS_CACHE, cache_key, response)
    return response


def day(
    delivery_date: date | None, run_id: str | None, day: date | None = None
) -> BriefDayResponse:
    """Compose the Brief's eight per-day requests behind one call.

    Resolves run/horizon once so every section reads the same artifact, then
    delegates to each section's own handler — pure composition, no duplicated
    query logic to drift out of sync with the single-section endpoints.

    The seven handlers run on a thread pool, not sequentially. Each is a sync,
    DB-bound function that opens its own connection (the pool budgets
    ``max_size=8``, so 7 concurrent checkouts fit); run one after another they
    would cost ``sum(sections)`` wall-clock instead of ``max(sections)``.
    """
    delivery_date = panels._resolve_brief_delivery_date(delivery_date, day)
    started = perf_counter()
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = panels._resolve_run(cur, run_id)
        horizon = panels._resolve_horizon(cur, run_id, delivery_date, None)
        final = horizon is not None and _brief_is_final(cur, delivery_date, horizon)
    key = (run_id, delivery_date, horizon)
    if final:
        cached = _brief_cache_get(key)
        if cached is not None:
            return cached
    with ThreadPoolExecutor(max_workers=7) as pool:
        sections = {
            "hero": pool.submit(
                _timed_brief_section,
                "hero",
                panels.get_hero,
                delivery_date,
                run_id,
                horizon,
            ),
            "context": pool.submit(
                _timed_brief_section,
                "context",
                panels.get_context,
                delivery_date,
                run_id,
                horizon,
                14,
            ),
            "standouts": pool.submit(
                _timed_brief_section,
                "standouts",
                panels.get_standouts,
                delivery_date,
                run_id,
                horizon,
                4,
            ),
            "top_nodes": pool.submit(
                _timed_brief_section,
                "top_nodes",
                panels.get_top_nodes,
                delivery_date,
                run_id,
                horizon,
                10,
            ),
            "top_constraints": pool.submit(
                _timed_brief_section,
                "top_constraints",
                panels.get_top_constraints,
                delivery_date,
                run_id,
                horizon,
                10,
            ),
            "grade": pool.submit(
                _timed_brief_section,
                "grade",
                panels.get_grade,
                delivery_date,
                run_id,
                horizon,
            ),
            "grade_history": pool.submit(
                _timed_brief_section,
                "grade_history",
                panels.get_grade_history,
                delivery_date,
                run_id,
                horizon,
                30,
            ),
        }
        completed = {name: future.result() for name, future in sections.items()}
        response = BriefDayResponse(
            hero=completed["hero"][1],
            context=completed["context"][1],
            standouts=completed["standouts"][1],
            top_nodes=completed["top_nodes"][1],
            top_constraints=completed["top_constraints"][1],
            grade=completed["grade"][1],
            grade_history=completed["grade_history"][1],
        )
    elapsed = perf_counter() - started
    if elapsed >= _BRIEF_SLOW_REQUEST_SECONDS:
        timings = ", ".join(
            f"{name}={result[2]:.3f}s" for name, result in completed.items()
        )
        logger.info(
            "brief_profile day=%s run=%s horizon=%s total=%.3fs %s",
            delivery_date,
            run_id,
            horizon,
            elapsed,
            timings,
        )
    if final:
        _brief_cache_put(key, response)
    return response
