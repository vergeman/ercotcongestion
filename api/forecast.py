"""GET /forecast_range — per-hour forecast congestion (P10/P50/P90) for a window.

The prediction counterpart to ``/ercot_spp_range``: same range shape, read from
``forecast_nodal``. ``run_id`` names the *model version* (not a day — one run
accumulates many ``delivery_date`` s); the public API serves the current
``forecast_current[ercot]`` run (this feature's own pointer, independent of the
SF-map ``map_run_id``). ``start``/``end``
scrub history; omitting both serves the run's latest ``delivery_date`` — a **UTC**
calendar day, so in CT it spans 19:00 → 18:00 (CDT), not midnight to midnight — the
default landing view. The left ("prediction") map pane consumes it through the same
prefetch/scrubber path the realized ranges use, so the two panes align hour for
hour instead of both rendering one realized quantity.

Expanded for prediction vs ``/ercot_spp_range``: each SP carries the P10/P50/P90
triple, and each hour carries the DAM ``system_lambda`` (NP4-523-CD) at that
interval — ``DISTINCT ON`` keeping the ``dst_flag = FALSE`` variant, matching
``/ercot_state_range`` — so predicted LMP = P50 + system_λ resolves on the client
against the same reference the market side subtracts. On an unsettled hour (no
DAM row yet) ``system_lambda`` falls back to the most recent settled day's λ at
the same Central hour — a persistence display convention (0130), never a model
input — and ``lambda_source`` says which curve served: ``"settled"`` or
``"persisted"``.

An empty window (no forecast hours for the current run in range, or no run
published) returns 503, matching the realized ranges' soft-fail contract.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from services.sf_artifacts import coerce_utc as _coerce_utc
from services.system_lambda import (
    forecast_system_lambda,
    persisted_system_lambdas_by_ct_hour,
    settled_system_lambdas,
)

from models import (
    ForecastRangeEntry,
    ForecastRangeResponse,
    ForecastSpState,
)

log = logging.getLogger(__name__)

router = APIRouter()


def _server_selected_run() -> None:
    """Keep forecast-run selection behind the server boundary for public reads."""
    return None

def _round_congestion(value: float | None) -> float | None:
    """The map has cent resolution; don't ship model float noise."""
    if value is None:
        return None
    return float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


@router.get(
    "/forecast_range",
    response_model=ForecastRangeResponse,
    summary="Per-hour forecast congestion (P10/P50/P90) per SP; "
    "defaults to the latest delivery day",
)
def get_forecast_range(
    run_id: str | None = Depends(_server_selected_run),
    start: datetime | None = Query(
        None,
        description="ISO-8601 UTC start (inclusive). Omit together with `end` "
        "to default to the run's latest delivery day (a UTC calendar day).",
    ),
    end: datetime | None = Query(
        None,
        description="ISO-8601 UTC end (inclusive). Omit together with `start` "
        "to default to the run's latest delivery day (a UTC calendar day).",
    ),
    horizon: int | None = Query(
        None,
        ge=1,
        le=2,
        description="Explicitly read one horizon track: 1 = final/t+1, 2 = "
        "preview/t+2 (0123). Omit to coalesce per day (prefer final, fall back to "
        "preview) into one continuous series. An explicit horizon with no rows for "
        "a day 404s (no fallback) — the 'what changed' view of a preserved preview.",
    ),
) -> ForecastRangeResponse:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Resolve the current promoted run — this feature's own pointer, not the SF-map
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
            # delivery day, as the actual ts span of its stored rows.
            #
            # That span is a **UTC** calendar day: `daily_forecast` forecasts
            # `pd.date_range(D, periods=24, freq="h", tz="UTC")`, so in CT the day
            # runs 19:00 -> 18:00 (CDT) / 18:00 -> 17:00 (CST), not midnight to
            # midnight. Reading the span from the rows keeps this endpoint honest
            # about what was actually published — including a short or missing day
            # — but it does NOT recover a CT operating day, and a client must not
            # assume it did. Note the default also hides a gap: it serves
            # MAX(delivery_date), so a missing day earlier in the run is invisible
            # here and only shows up when someone scrubs onto it.
            # A `?horizon=` (1|2) reads exactly that track; omitted, the window
            # default and the main read both coalesce per day, preferring the final
            # (horizon 1) over the preview (horizon 2). The horizon clause is shared
            # by the default-window probe and the main read so both agree.
            hz_clause = "" if horizon is None else " AND horizon = %s"
            hz_args: tuple = () if horizon is None else (horizon,)

            if start is not None and end is not None:
                start_u = _coerce_utc(start)
                end_u = _coerce_utc(end)
            else:
                cur.execute(
                    f"""
                    SELECT MIN(ts) AS lo, MAX(ts) AS hi
                    FROM forecast_nodal
                    WHERE run_id = %s{hz_clause} AND delivery_date = (
                        SELECT MAX(delivery_date)
                        FROM forecast_nodal WHERE run_id = %s{hz_clause}
                    )
                    """,
                    (run_id, *hz_args, run_id, *hz_args),
                )
                span = cur.fetchone()
                if span is None or span["lo"] is None:
                    # Explicit horizon with nothing published is a 404 (that track
                    # does not exist for this run); the coalesced default keeps the
                    # realized-range 503 soft-fail contract.
                    raise HTTPException(
                        status_code=404 if horizon is not None else 503,
                        detail=f"run_id={run_id}"
                        + (f" horizon={horizon}" if horizon is not None else "")
                        + " has no forecast_nodal rows to default a window from.",
                    )
                start_u = _coerce_utc(span["lo"])
                end_u = _coerce_utc(span["hi"])

            # Coalesce per (ts, sp): DISTINCT ON keeping the lowest horizon present —
            # the final when it exists, else the preview. Ordering by horizon ASC
            # makes horizon 1 win. With an explicit horizon the filter already pins
            # one track, so the DISTINCT ON is a harmless no-op. `delivery_date` +
            # `horizon` ride along so the response can report per-day provenance.
            cur.execute(
                f"""
                SELECT DISTINCT ON (ts, settlement_point)
                       ts, settlement_point, p10, p50, p90, delivery_date, horizon
                FROM forecast_nodal
                WHERE run_id = %s AND ts >= %s AND ts <= %s{hz_clause}
                ORDER BY ts, settlement_point, horizon ASC
                """,
                (run_id, start_u, end_u, *hz_args),
            )
            rows = cur.fetchall()

            # System-λ at each forecast hour in range — the shared LMP reference.
            lam_by_ts_raw = settled_system_lambdas(cur, start_u, end_u)

            # Persistence λ (0130): unsettled hours (the DAM hasn't posted yet) get
            # no row above. Fill them from the most recent settled day's curve by
            # Central hour — a display convention, not a model, so this never
            # touches a graded surface. Only queried when the window actually needs
            # it (a pure history scrub is fully settled and skips this).
            unsettled = {
                _coerce_utc(r["ts"])
                for r in rows
                if _coerce_utc(r["ts"]) not in lam_by_ts_raw
            }
            persisted_by_hour = persisted_system_lambdas_by_ct_hour(cur) if unsettled else {}

    if not rows:
        # Explicit horizon with no rows → 404 (no fallback to the other track); the
        # coalesced default keeps the realized-range 503 soft-fail contract.
        raise HTTPException(
            status_code=404 if horizon is not None else 503,
            detail=(
                f"no forecast_nodal rows for run_id={run_id}"
                + (f" horizon={horizon}" if horizon is not None else "")
                + f" in window {start_u} .. {end_u}. "
                "The served forecast run has no hours here."
            ),
        )

    # Per-delivery-day horizon provenance (0123): every (ts, sp) of a day carries the
    # same coalesced horizon, so any row of the day fixes it — 1 = final, 2 = preview.
    horizons_map: dict[str, int] = {}
    by_ts: dict[datetime, list[ForecastSpState]] = {}
    for r in rows:
        ts = _coerce_utc(r["ts"])
        horizons_map[r["delivery_date"].isoformat()] = int(r["horizon"])
        by_ts.setdefault(ts, []).append(
            ForecastSpState(
                sp_id=str(r["settlement_point"]),
                p10=_round_congestion(r["p10"]),
                p50=_round_congestion(r["p50"]),
                p90=_round_congestion(r["p90"]),
            )
        )

    entries = []
    for ts, sps in sorted(by_ts.items()):
        lam, lam_source = forecast_system_lambda(ts, lam_by_ts_raw, persisted_by_hour)
        entries.append(
            ForecastRangeEntry(
                interval_ts=ts,
                system_lambda=lam,
                lambda_source=lam_source,
                sps=sps,
            )
        )

    return ForecastRangeResponse(
        start=start_u,
        end=end_u,
        run_id=run_id,
        count=len(entries),
        entries=entries,
        horizons=horizons_map,
    )
