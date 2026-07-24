"""GET /matrix/frame — a bounded causal SF rectangle for one delivery hour."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from models import MatrixColumn, MatrixFrame, MatrixRow, MatrixSfValues
from services.sf_artifacts import load_daily_artifact, normalize_constraint_key


router = APIRouter(prefix='/matrix')

CENTRAL = ZoneInfo('America/Chicago')
DEFAULT_ROW_LIMIT = 30
DEFAULT_COLUMN_LIMIT = 40
MAX_ROW_LIMIT = 100
MAX_COLUMN_LIMIT = 100

# Metadata is deliberately best-effort: the artifact is authoritative for the
# matrix itself, and an absent topology record must not change its shape.
_SP_METADATA: dict[str, tuple[str | None, str | None]] | None = None


def _coerce_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _delivery_date(ts: datetime):
    """ERCOT operating date, including the Central-time midnight boundary."""
    return _coerce_utc(ts).astimezone(CENTRAL).date()


def _split_constraint_key(key: str) -> tuple[str, str | None]:
    name, sep, contingency = str(key).partition('|')
    return name, contingency if sep else None


def _sp_metadata() -> dict[str, tuple[str | None, str | None]]:
    global _SP_METADATA
    if _SP_METADATA is None:
        # Keep this import local: pandas and the topology CSV are not needed to
        # resolve missing artifacts.
        from shared.settings import settings
        try:
            df = pd.read_csv(settings.settlement_points_geocoded_csv)
        except FileNotFoundError:
            _SP_METADATA = {}
        else:
            def load_zone(sp: str) -> str | None:
                if sp.startswith('LZ_'):
                    return sp[3:].lower() or None
                if sp.startswith('HB_'):
                    return f'{sp[3:].lower()}_hub' if sp[3:] else None
                return None
            _SP_METADATA = {
                str(r.settlement_point): (
                    None if pd.isna(getattr(r, 'sp_type', None)) else str(getattr(r, 'sp_type')),
                    load_zone(str(r.settlement_point)),
                )
                for r in df.itertuples(index=False)
            }
    return _SP_METADATA


def _unavailable(run_id: str, delivery_date, interval_ts: datetime, reason: str) -> MatrixFrame:
    return MatrixFrame(
        available=False,
        unavailable_reason=reason,
        run_id=run_id,
        delivery_date=delivery_date,
        interval_ts=interval_ts,
        sf=MatrixSfValues(row_count=0, column_count=0, values=[]),
    )


def _dam_mu(cur, interval_ts: datetime) -> dict[str, float]:
    """Exact-hour published DAM μ keyed exactly like the artifact vocabulary."""
    cur.execute(
        "SELECT constraint_name, contingency_name, sum(shadow_price) AS shadow_price "
        "FROM ercot_dam_shadow_prices WHERE interval_ts = %s AND shadow_price IS NOT NULL "
        "GROUP BY constraint_name, contingency_name",
        (interval_ts,),
    )
    return {
        normalize_constraint_key(r['constraint_name'], r['contingency_name']): float(r['shadow_price'])
        for r in cur.fetchall()
        if r['shadow_price'] is not None
    }


@router.get('/frame', response_model=MatrixFrame, summary='Bounded causal SF matrix frame')
def get_matrix_frame(
    interval_ts: datetime = Query(..., description='Delivery interval in ISO-8601 UTC.'),
    row_limit: int = Query(DEFAULT_ROW_LIMIT, ge=1, le=MAX_ROW_LIMIT),
    column_limit: int = Query(DEFAULT_COLUMN_LIMIT, ge=1, le=MAX_COLUMN_LIMIT),
    column_set: str = Query('core', pattern='^core$', description='Frozen column selection.'),
) -> MatrixFrame:
    del column_set  # Reserved for future named sets; only the causal core set exists today.
    interval_ts = _coerce_utc(interval_ts)
    delivery_date = _delivery_date(interval_ts)

    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=503, detail='no forecast run is published yet.')
        run_id = str(row['run_id'])

        artifact = load_daily_artifact(cur, run_id, delivery_date)
        if artifact is None:
            return _unavailable(run_id, delivery_date, interval_ts, 'artifact_missing')

        hour = pd.Timestamp(interval_ts)
        if hour not in artifact.E_mu.index:
            return _unavailable(run_id, delivery_date, interval_ts, 'interval_not_in_artifact')

        # Freeze rows from the whole day, never from the selected hour. The
        # contribution mass is the artifact's causal μ multiplied by its recovered
        # SF reach; ties are explicit so refreshes cannot shuffle labels.
        mu_mass = artifact.E_mu.abs().sum(axis=0)
        reach = artifact.SF.abs().sum(axis=1)
        contribution = (mu_mass * reach).astype(float)
        row_keys = sorted(artifact.SF.index, key=lambda key: (-contribution.loc[key], str(key)))[:row_limit]

        # The core column universe is likewise day-stable, but scoped to the
        # frozen rows so widening row_limit is the only way it can change.
        row_sf = artifact.SF.loc[row_keys]
        col_max = row_sf.abs().max(axis=0)
        column_keys = sorted(row_sf.columns, key=lambda key: (-col_max.loc[key], str(key)))[:column_limit]

        dam_by_key = _dam_mu(cur, interval_ts)

    exact_mu = artifact.E_mu.loc[hour]
    metadata = _sp_metadata()
    rows: list[MatrixRow] = []
    matched_dam = 0
    for rank, key in enumerate(row_keys, start=1):
        name, contingency = _split_constraint_key(str(key))
        dam_mu = dam_by_key.get(str(key))
        matched_dam += dam_mu is not None
        rows.append(MatrixRow(
            constraint_key=str(key), constraint_name=name, contingency_name=contingency,
            forecast_mu=float(exact_mu.loc[key]), ercot_dam_mu=dam_mu,
            daily_rank=rank,
            binding_hours=int((artifact.E_mu[key].abs() > 0).sum()),
            max_abs_sf=float(artifact.SF.loc[key].abs().max()),
        ))
    columns = [
        MatrixColumn(
            settlement_point=str(key), settlement_point_type=metadata.get(str(key), (None, None))[0],
            load_zone=metadata.get(str(key), (None, None))[1], max_abs_sf=float(col_max.loc[key]),
        )
        for key in column_keys
    ]
    dam_status = 'available' if matched_dam == len(rows) else ('partial' if matched_dam else 'pending')
    values = [float(value) for value in row_sf.loc[row_keys, column_keys].to_numpy().ravel()]
    return MatrixFrame(
        available=True, run_id=run_id, delivery_date=delivery_date, interval_ts=interval_ts,
        dam_status=dam_status, rows=rows, columns=columns,
        sf=MatrixSfValues(row_count=len(rows), column_count=len(columns), values=values),
    )
