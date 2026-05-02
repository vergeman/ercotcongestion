"""GET /api/validation — regime-bucketed correlation: fragility vs |basis|.

Computes Pearson correlation between per-bus fragility and |basis| over a
user-selected window. Splits snapshots into "congested" (n_binding_lines >=
threshold) and "quiet" buckets so the user can see whether the model carries
explanatory power specifically when the grid is stressed.

The threshold is configurable via query param; default is 1 (any binding line
counts as congested). Buses are filtered to those with both fragility and
basis present.

Also returns a small sample of (fragility, |basis|) points for the scatter
plot — capped to keep responses light.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query

from config import MAX_STATE_RANGE_HOURS, MIN_VALIDATION_HOURS
from db import get_pool
from models import CorrelationResult, ValidationResponse, ScatterPoint

router = APIRouter()

# Cap on scatter points returned. The browser renders these as SVG circles;
# 5k is plenty to see structure without bogging down the DOM.
SCATTER_CAP = 5000


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _pearson(pairs: Iterable[tuple[float, float]]) -> CorrelationResult:
    """Single-pass Pearson correlation. Returns rho=None for degenerate data."""
    n = 0
    sx = sy = sxx = syy = sxy = 0.0
    for x, y in pairs:
        n += 1
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y

    if n < 2:
        return CorrelationResult(n=n, rho=None)

    # Variance check — if either is zero, correlation is undefined.
    var_x = sxx - sx * sx / n
    var_y = syy - sy * sy / n
    if var_x <= 0 or var_y <= 0:
        return CorrelationResult(n=n, rho=None)

    cov = sxy - sx * sy / n
    rho = cov / math.sqrt(var_x * var_y)
    # Guard against tiny float overshoot.
    rho = max(-1.0, min(1.0, rho))
    return CorrelationResult(n=n, rho=rho)

#
# ROUTER
#

@router.get(
    '/validation',
    response_model=ValidationResponse,
    summary='Regime-bucketed correlation between fragility and |basis|',
)
def get_validation(
    start: datetime = Query(..., description='ISO-8601 UTC start (inclusive)'),
    end:   datetime = Query(..., description='ISO-8601 UTC end (exclusive)'),
    congested_threshold: int = Query(
        1, ge=1,
        description='Snapshots with n_binding_lines >= this are "congested"',
    ),
) -> ValidationResponse:
    s = _coerce_utc(start)
    e = _coerce_utc(end)
    if e <= s:
        raise HTTPException(status_code=400, detail='end must be after start')

    span_hours = (e - s).total_seconds() / 3600
    if span_hours > MAX_STATE_RANGE_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f'Range exceeds {MAX_STATE_RANGE_HOURS}h cap; got {span_hours:.0f}h',
        )

    warnings: list[str] = []
    if span_hours < MIN_VALIDATION_HOURS:
        warnings.append(
            f'Window is {span_hours:.1f}h; recommended minimum is '
            f'{MIN_VALIDATION_HOURS}h for stable correlation estimates.'
        )

    # Single query: join bus_snapshots to snapshot_meta for the regime tag,
    # plus a LEFT JOIN to bus_load_zones so each row also carries its zone
    # Filter at the SQL layer keeps Python-side bookkeeping minimal.
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    bs.fragility,
                    bs.basis,
                    (sm.n_binding_lines >= %s) AS is_congested,
                    blz.load_zone
                FROM bus_snapshots bs
                JOIN snapshot_meta sm ON sm.interval_ts = bs.interval_ts
                LEFT JOIN bus_load_zones blz ON blz.bus_id = bs.bus_id
                WHERE bs.interval_ts >= %s AND bs.interval_ts < %s
                  AND sm.status = 'ok'
                  AND bs.fragility IS NOT NULL
                  AND bs.basis IS NOT NULL
                """,
                (congested_threshold, s, e),
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*)
                FROM snapshot_meta
                WHERE interval_ts >= %s AND interval_ts < %s
                  AND status = 'ok'
                """,
                (s, e),
            )
            n_snapshots = cur.fetchone()[0]

    if not rows:
        return ValidationResponse(
            start=s, end=e,
            n_snapshots=n_snapshots,
            n_observations=0,
            overall=CorrelationResult(n=0, rho=None),
            congested=CorrelationResult(n=0, rho=None),
            quiet=CorrelationResult(n=0, rho=None),
            congested_threshold_n_binding=congested_threshold,
            scatter=[],
            by_zone={},
            warnings=warnings + ['No (fragility, basis) observations in window.'],
        )

    # Build pair generators per bucket. We make three passes over the result
    # set; with O(100k) rows this is trivial. Using |basis| since basis sign
    # is direction info we don't need for correlation magnitude.
    overall_pairs = ((r[0], abs(r[1])) for r in rows)
    congested_pairs = ((r[0], abs(r[1])) for r in rows if r[2])
    quiet_pairs     = ((r[0], abs(r[1])) for r in rows if not r[2])

    overall   = _pearson(overall_pairs)
    congested = _pearson(congested_pairs)
    quiet     = _pearson(quiet_pairs)

    # Per-zone breakdown. Skip rows without a zone (NULL from the LEFT JOIN)
    # and drop the 'non_ercot' fallback bucket — neither tells us anything
    # about ERCOT model performance. Group with a dict-of-lists; with O(100k)
    # rows and ~4 zones this is negligible memory.
    pairs_by_zone: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        zone = r[3]
        if zone is None or zone == 'non_ercot':
            continue
        pairs_by_zone.setdefault(zone, []).append((r[0], abs(r[1])))
    by_zone = {z: _pearson(p) for z, p in pairs_by_zone.items()}

    # Scatter sample. If we're under the cap take everything; otherwise stride
    # so we get a uniform sample across the window rather than a head-of-list
    # bias. Stride sampling keeps it deterministic and avoids importing random.
    n_total = len(rows)
    if n_total <= SCATTER_CAP:
        sample_idx = range(n_total)
    else:
        stride = n_total / SCATTER_CAP
        sample_idx = (int(i * stride) for i in range(SCATTER_CAP))

    scatter = [
        ScatterPoint(
            fragility=rows[i][0],
            abs_basis=abs(rows[i][1]),
            congested=bool(rows[i][2]),
        )
        for i in sample_idx
    ]

    return ValidationResponse(
        start=s, end=e,
        n_snapshots=n_snapshots,
        n_observations=n_total,
        overall=overall,
        congested=congested,
        quiet=quiet,
        congested_threshold_n_binding=congested_threshold,
        scatter=scatter,
        by_zone=by_zone,
        warnings=warnings,
    )
