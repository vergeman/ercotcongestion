"""GET /ercot_state_range — per-hour ERCOT SP congestion for a window.

Reads the currently-served run's ``matrix/congestion_matrices.npz`` under
``settings.served_run_dir``. Keys are namespaced by reference method —
``<ref>_ercot_C``, ``<ref>_ercot_sp_ids``, ``<ref>_ercot_hours`` — matching
``compute.mapping.correlation_map``.

The ref itself is not a separate env var: it is read from the served
``mapping/scorecard.json``'s ``params.ref`` field, with an in-process
cache invalidated when the JSON's mtime changes. Promoting a scorecard
cell built against a different ref automatically switches the ERCOT
column served here. If we ever need to serve a scorecard on one ref and
ERCOT-state on another, add a per-endpoint override then — not up front.

Missing artifacts return 503 rather than synthesising values.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from models import ErcotSpState, ErcotStateRangeEntry, ErcotStateRangeResponse
from shared.settings import settings

log = logging.getLogger(__name__)

router = APIRouter()


def _matrix_path() -> Path:
    return Path(settings.served_run_dir) / "matrix" / "congestion_matrices.npz"


def _scorecard_json_path() -> Path:
    return Path(settings.served_run_dir) / "mapping" / "scorecard.json"


# In-process cache of the last (mtime_ns, ref) pair. Cleared whenever the
# scorecard file the symlink resolves to changes mtime — a symlink flip
# by ``compute.promote`` counts because ``os.stat`` follows the link.
_REF_CACHE: dict[str, tuple[int, str]] = {}


def _read_served_ref() -> str:
    """Return ``params.ref`` from the served scorecard.json, mtime-cached."""
    path = _scorecard_json_path()
    try:
        mtime = os.stat(path).st_mtime_ns
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no scorecard is currently served (missing {path}). "
                f"Promote a run with: python -m compute.promote."
            ),
        ) from exc

    key = str(path)
    cached = _REF_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    with open(path) as f:
        params = json.load(f).get("params", {})
    ref = params.get("ref")
    if not ref:
        raise HTTPException(
            status_code=503,
            detail=f"served scorecard {path} has no params.ref",
        )
    _REF_CACHE[key] = (mtime, ref)
    return ref


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@router.get(
    "/ercot_state_range",
    response_model=ErcotStateRangeResponse,
    summary="ERCOT SP congestion snapshots across a window",
)
def get_ercot_state_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> ErcotStateRangeResponse:
    path = _matrix_path()
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"congestion matrices not built for served run; missing {path}",
        )

    ref = _read_served_ref()
    with np.load(path, allow_pickle=False) as z:
        keys = {
            "C": f"{ref}_ercot_C",
            "sp_ids": f"{ref}_ercot_sp_ids",
            "hours": f"{ref}_ercot_hours",
        }
        missing = [k for k in keys.values() if k not in z.files]
        if missing:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"ercot matrix keys missing for ref={ref}: {missing}. "
                    f"Regenerate with ercot_ref={ref}."
                ),
            )
        C = z[keys["C"]]
        sp_ids = z[keys["sp_ids"]]
        hours = z[keys["hours"]]

    if C.size == 0 or hours.size == 0:
        raise HTTPException(
            status_code=503,
            detail=f"ercot matrix empty for ref={ref}",
        )

    start_u = _coerce_utc(start)
    end_u = _coerce_utc(end)

    # Parse each stored hour string once. Store as tz-aware UTC.
    # The stored form is ``<scenario_label>|<iso8601>`` — split off the
    # leading label before parsing.
    def _parse(h: str) -> datetime:
        iso = h.split("|", 1)[-1]
        return _coerce_utc(datetime.fromisoformat(iso))

    parsed = np.array([_parse(str(h)) for h in hours.tolist()])
    mask = np.array([start_u <= t <= end_u for t in parsed])
    hit_idx = np.where(mask)[0]

    sp_ids_list = [str(s) for s in sp_ids.tolist()]
    entries: list[ErcotStateRangeEntry] = []
    for i in hit_idx:
        col = C[:, i]
        sps = [
            ErcotSpState(
                sp_id=sp_ids_list[j],
                congestion=None if not np.isfinite(v) else float(v),
            )
            for j, v in enumerate(col)
        ]
        entries.append(ErcotStateRangeEntry(interval_ts=parsed[i], sps=sps))

    return ErcotStateRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
