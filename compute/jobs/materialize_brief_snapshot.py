"""Write immutable Brief JSONB snapshots after settlement."""
from __future__ import annotations

from datetime import date

from psycopg_pool import ConnectionPool

from api import db
from api.services.analysis import brief
from shared.settings import settings


def materialize_day(run_id: str, delivery_date: date, horizon: int) -> bool:
    """Materialize one final Brief day using the API's panel composition."""
    if horizon != 1:
        return False
    pool = ConnectionPool(
        conninfo=settings.pg_dsn,
        min_size=1,
        max_size=8,
        kwargs={"autocommit": True},
    )
    pool.wait()
    previous = db.pool
    db.pool = pool
    try:
        return brief.materialize_final_snapshot(run_id, delivery_date, horizon)
    finally:
        db.pool = previous
        pool.close()
