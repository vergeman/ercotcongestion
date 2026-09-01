"""Database collaborators for the Matrix frame service."""

from dataclasses import dataclass
from datetime import date, datetime

from psycopg.rows import dict_row

from api.services.sf_artifacts import load_daily_artifact, load_realized_mu


@dataclass(frozen=True)
class MatrixArtifactContext:
    run_id: str
    artifact: object | None


class MatrixRepository:
    """Own Matrix's small set of SQL lookups without owning artifact caching."""

    def __init__(self, pool) -> None:
        self._pool = pool

    def artifact_context(self, delivery_date: date) -> MatrixArtifactContext | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                return None
            run_id = str(row["run_id"])
            return MatrixArtifactContext(
                run_id, load_daily_artifact(cur, run_id, delivery_date)
            )

    def realized_mu(self, interval_ts: datetime, constraint_keys) -> dict[str, float]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            return load_realized_mu(cur, [interval_ts], constraint_keys).to_dict()

    def constraint_types(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT DISTINCT ON (constraint_key) constraint_key, ctype FROM constraint_geo "
                "WHERE constraint_key = ANY(%s) ORDER BY constraint_key, window_start DESC",
                (keys,),
            )
            return {
                str(row["constraint_key"]): str(row["ctype"])
                for row in cur.fetchall()
                if row["ctype"] is not None
            }
