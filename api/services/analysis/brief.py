"""Composition service for the Analysis Brief endpoints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import json
import logging
from time import perf_counter
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row

from api.services.analysis import panels
from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (
    BriefDayResponse,
    BriefDetailsResponse,
    BriefHeroShellResponse,
)

logger = logging.getLogger(__name__)
_CT = ZoneInfo("America/Chicago")
_BRIEF_SLOW_REQUEST_SECONDS = 1.0
_SNAPSHOT_SCHEMA_VERSION = 1


def _snapshot_get(cur, key: tuple[str, date, int]):
    cur.execute(
        "SELECT hero, details, standouts FROM brief_daily_snapshot "
        "WHERE run_id = %s AND delivery_date = %s AND horizon = %s "
        "AND schema_version = %s",
        (*key, _SNAPSHOT_SCHEMA_VERSION),
    )
    return cur.fetchone()


def _snapshot_put(conn, key: tuple[str, date, int], snapshot: dict):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "INSERT INTO brief_daily_snapshot "
            "(run_id, delivery_date, horizon, schema_version, hero, details, standouts) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, delivery_date, horizon) DO UPDATE SET "
            "schema_version = EXCLUDED.schema_version, hero = EXCLUDED.hero, "
            "details = EXCLUDED.details, standouts = EXCLUDED.standouts, computed_at = now() "
            "WHERE brief_daily_snapshot.schema_version <> EXCLUDED.schema_version",
            (*key, _SNAPSHOT_SCHEMA_VERSION, Jsonb(snapshot["hero"]),
             Jsonb(snapshot["details"]), Jsonb(snapshot["standouts"])),
        )
        stored = _snapshot_get(cur, key)
    return stored


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


def _snapshot_payload(
    day: date, run_id: str, horizon: int
) -> dict[str, dict]:
    """Compose the immutable panels once for a settled delivery day."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        hero_future = pool.submit(panels.get_hero, day, run_id, horizon)
        details_future = pool.submit(
            _compose_brief_details, day, run_id, horizon, include_standouts=False
        )
        standouts_future = pool.submit(panels.get_standouts, day, run_id, horizon, 4)
        hero = hero_future.result()
        details = details_future.result()
        standouts = standouts_future.result()
    return {
        "hero": _json_payload(hero),
        "details": _json_payload(details),
        "standouts": _json_payload(standouts),
    }


def _json_payload(response) -> dict:
    return json.loads(
        json.dumps(jsonable_encoder(response), default=str),
        parse_constant=lambda _: None,
    )


def _snapshot_or_compose(
    key: tuple[str, date, int]
) -> dict:
    """Return a settled Brief snapshot, allowing one writer across API pods."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        stored = _snapshot_get(cur, key)
    if stored is not None:
        return stored
    snapshot = _snapshot_payload(key[1], key[0], key[2])
    with get_pool().connection() as conn:
        return _snapshot_put(conn, key, snapshot)


def materialize_final_snapshot(run_id: str, delivery_date: date, horizon: int) -> bool:
    """Write one settled Brief snapshot for the forecast job."""
    key = (run_id, delivery_date, horizon)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if _snapshot_get(cur, key) is not None:
            return True
        if not _brief_is_final(cur, delivery_date, horizon):
            return False
    snapshot = _snapshot_payload(delivery_date, run_id, horizon)
    with get_pool().connection() as conn:
        _snapshot_put(conn, key, snapshot)
    return True


def _snapshot_details(snapshot: dict, *, include_standouts: bool) -> BriefDetailsResponse:
    if not include_standouts:
        return BriefDetailsResponse.model_validate(snapshot["details"])
    return BriefDetailsResponse.model_validate(
        {**snapshot["details"], "standouts": snapshot["standouts"]}
    )


def hero_shell(
    delivery_date: date | None, run_id: str | None, day: date | None = None
) -> BriefHeroShellResponse:
    """Serve the Brief prose and map before its slower stat-card evidence."""
    delivery_date = panels._resolve_brief_delivery_date(delivery_date, day)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = panels._resolve_run(cur, run_id)
        horizon = panels._resolve_horizon(cur, run_id, delivery_date, None)
        final = horizon is not None and _brief_is_final(cur, delivery_date, horizon)
        previous, following = _brief_neighbor_dates(cur, run_id, delivery_date)
    if final:
        snapshot = _snapshot_or_compose((run_id, delivery_date, horizon))
        hero = snapshot["hero"]
    else:
        hero = panels.get_hero(delivery_date, run_id, horizon)
    response = BriefHeroShellResponse(
        hero=hero,
        previous_delivery_date=previous,
        next_delivery_date=following,
    )
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
        final = horizon is not None and _brief_is_final(cur, delivery_date, horizon)
    if final:
        return _snapshot_details(
            _snapshot_or_compose((run_id, delivery_date, horizon)),
            include_standouts=include_standouts,
        )
    response = _compose_brief_details(
        delivery_date, run_id, horizon, include_standouts=include_standouts
    )
    return response


def standouts(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    k: int = Query(4, ge=1, le=20),
):
    """Serve the root Brief's durable k=4 standouts payload when final."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = panels._resolve_run(cur, run_id)
        horizon = panels._resolve_horizon(cur, run_id, delivery_date, horizon)
        final = horizon is not None and _brief_is_final(cur, delivery_date, horizon)
    if final and k == 4:
        return _snapshot_or_compose((run_id, delivery_date, horizon))["standouts"]
    return panels.get_standouts(delivery_date, run_id, horizon, k)


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
    if final:
        snapshot = _snapshot_or_compose((run_id, delivery_date, horizon))
        details = _snapshot_details(snapshot, include_standouts=True)
        return BriefDayResponse(
            hero=snapshot["hero"],
            context=details.context,
            standouts=details.standouts,
            top_nodes=details.top_nodes,
            top_constraints=details.top_constraints,
            grade=details.grade,
            grade_history=details.grade_history,
        )
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
    return response
