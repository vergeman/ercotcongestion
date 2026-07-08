"""GET /api/meta — what the API is currently serving.

Read-only, no query params. Every field is derived from the promote
artifacts:

* ``run_id`` — basename of what ``served_run_dir`` resolves to (the
  ``current`` symlink target).
* ``ref``, ``algo``, ``k`` — from the served
  ``<served_run_dir>/mapping/scorecard.json``'s ``params`` block.
* ``promoted_at`` — the ``implied_binding_proximity_current[ercot]``
  pointer's timestamp.

Any of these can be ``None`` — the endpoint never 5xxs on missing state
because a debug/footer UI wants a truthful snapshot including "nothing
promoted yet", not an error.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from psycopg.rows import dict_row

from db import get_pool
from models import MetaResponse
from shared.settings import settings

log = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_LAYER = "ercot"


def _served_run_id() -> str | None:
    """Return the run_id ``served_run_dir`` resolves to, or None if unset."""
    served = settings.served_run_dir
    try:
        real = os.path.realpath(served)
    except OSError:
        return None
    if not os.path.exists(real):
        return None
    name = os.path.basename(real)
    return name or None


def _scorecard_params() -> dict:
    """Read the served scorecard's ``params`` block, or {} if absent."""
    path = Path(settings.served_run_dir) / "mapping" / "scorecard.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f).get("params", {}) or {}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read served scorecard %s: %s", path, exc)
        return {}


def _ibp_promoted_at(layer: str) -> datetime | None:
    """Return ``promoted_at`` for the IBP layer, or None if unset."""
    try:
        pool = get_pool()
    except Exception as exc:
        log.warning("meta: DB pool unavailable: %s", exc)
        return None
    try:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT promoted_at FROM implied_binding_proximity_current "
                "WHERE layer = %s",
                (layer,),
            )
            row = cur.fetchone()
            return row["promoted_at"] if row else None
    except Exception as exc:
        log.warning("meta: could not read IBP pointer for layer=%s: %s", layer, exc)
        return None


@router.get(
    "/meta",
    response_model=MetaResponse,
    summary="What run/cell the API is currently serving",
)
def get_meta() -> MetaResponse:
    params = _scorecard_params()
    k = params.get("k")
    return MetaResponse(
        run_id=_served_run_id(),
        ref=params.get("ref"),
        algo=params.get("algo"),
        k=int(k) if k is not None else None,
        promoted_at=_ibp_promoted_at(DEFAULT_LAYER),
    )
