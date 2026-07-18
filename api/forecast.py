"""GET /forecast_range — per-hour forecast congestion (P10/P50/P90) for a window.

The prediction counterpart to ``/ercot_spp_range``: same range shape, read from
``forecast_nodal``. ``run_id`` names the *model version* (not a day — one run
accumulates many ``delivery_date`` s); an explicit ``?run_id=`` selects a version
to A/B, and omitting it serves the current ``forecast_current[ercot]`` run (this
feature's own pointer, independent of the SF-map ``map_run_id``). ``start``/``end``
scrub history; omitting both serves the run's latest operating day — the default
landing view. The left ("prediction") map pane consumes it through the same
prefetch/scrubber path the realized ranges use, so the two panes align hour for
hour instead of both rendering one realized quantity.

Expanded for prediction vs ``/ercot_spp_range``: each SP carries the P10/P50/P90
triple, and each hour carries the DAM ``system_lambda`` (NP4-523-CD) at that
interval — ``DISTINCT ON`` keeping the ``dst_flag = FALSE`` variant, matching
``/ercot_state_range`` — so predicted LMP = P50 + system_λ resolves on the client
against the same reference the market side subtracts.

An empty window (no forecast hours for the current run in range, or no run
published) returns 503, matching the realized ranges' soft-fail contract.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import (
    ForecastRangeEntry,
    ForecastRangeResponse,
    ForecastSpState,
)

log = logging.getLogger(__name__)

router = APIRouter()


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@router.get(
    "/forecast_range",
    response_model=ForecastRangeResponse,
    summary="Per-hour forecast congestion (P10/P50/P90) per SP; "
    "defaults to the latest operating day",
)
def get_forecast_range(
    run_id: str | None = Query(
        None,
        description="Model version to serve. Omit for the current promoted "
        "run (forecast_current[ercot]).",
    ),
    start: datetime | None = Query(
        None,
        description="ISO-8601 UTC start (inclusive). Omit together with `end` "
        "to default to the run's latest operating day.",
    ),
    end: datetime | None = Query(
        None,
        description="ISO-8601 UTC end (inclusive). Omit together with `start` "
        "to default to the run's latest operating day.",
    ),
) -> ForecastRangeResponse:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Resolve the model version: an explicit ?run_id= wins; otherwise the
            # current promoted run — this feature's own pointer, not the SF-map
            # run. 503 (not empty) when nothing is published yet, so the client
            # renders the realized pane alone rather than erroring.
            if run_id is None:
                cur.execute(
                    "SELECT run_id FROM forecast_current WHERE layer = 'ercot'"
                )
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(
                        status_code=503,
                        detail="no forecast run is published yet "
                        "(forecast_current is empty).",
                    )
                run_id = row["run_id"]
            assert run_id is not None  # resolved from param or pointer above

            # Resolve the window. An explicit start+end is a history scrub; with
            # neither (the default landing view) we serve the run's latest
            # operating day — its actual ts span, so the CT operating day and its
            # DST offset come from the stored rows rather than UTC-midnight
            # arithmetic on the client.
            if start is not None and end is not None:
                start_u = _coerce_utc(start)
                end_u = _coerce_utc(end)
            else:
                cur.execute(
                    """
                    SELECT MIN(ts) AS lo, MAX(ts) AS hi
                    FROM forecast_nodal
                    WHERE run_id = %s AND delivery_date = (
                        SELECT MAX(delivery_date)
                        FROM forecast_nodal WHERE run_id = %s
                    )
                    """,
                    (run_id, run_id),
                )
                span = cur.fetchone()
                if span is None or span["lo"] is None:
                    raise HTTPException(
                        status_code=503,
                        detail=f"run_id={run_id} has no forecast_nodal rows to "
                        "default a window from.",
                    )
                start_u = _coerce_utc(span["lo"])
                end_u = _coerce_utc(span["hi"])

            cur.execute(
                """
                SELECT ts, settlement_point, p10, p50, p90
                FROM forecast_nodal
                WHERE run_id = %s AND ts >= %s AND ts <= %s
                ORDER BY ts, settlement_point
                """,
                (run_id, start_u, end_u),
            )
            rows = cur.fetchall()

            # System-λ at each forecast hour in range — the shared LMP reference.
            cur.execute(
                """
                SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
                FROM dam_system_lambda
                WHERE interval_ts >= %s AND interval_ts <= %s
                ORDER BY interval_ts, dst_flag ASC
                """,
                (start_u, end_u),
            )
            lam_rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no forecast_nodal rows for run_id={run_id} in window "
                f"{start_u} .. {end_u}. The served forecast run has no hours here."
            ),
        )

    lam_by_ts: dict[datetime, float | None] = {
        _coerce_utc(r["interval_ts"]): (
            None if r["system_lambda"] is None else float(r["system_lambda"])
        )
        for r in lam_rows
    }

    by_ts: dict[datetime, list[ForecastSpState]] = {}
    for r in rows:
        ts = _coerce_utc(r["ts"])
        by_ts.setdefault(ts, []).append(
            ForecastSpState(
                sp_id=str(r["settlement_point"]),
                p10=r["p10"],
                p50=r["p50"],
                p90=r["p90"],
            )
        )

    entries = [
        ForecastRangeEntry(
            interval_ts=ts,
            system_lambda=lam_by_ts.get(ts),
            sps=sps,
        )
        for ts, sps in sorted(by_ts.items())
    ]

    return ForecastRangeResponse(
        start=start_u,
        end=end_u,
        run_id=run_id,
        count=len(entries),
        entries=entries,
    )
