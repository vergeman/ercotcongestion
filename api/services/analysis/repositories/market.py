"""Market and ESSP reads used by Analysis feature services."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from api.schemas.analysis import NodeMarketState
from api.services.system_lambda import (
    forecast_system_lambda,
    persisted_system_lambdas_by_ct_hour,
    settled_system_lambdas,
)


def settled_congestion(
    cur, settlement_points: list[str], timestamps: pd.DatetimeIndex
) -> dict[str, float]:
    params = (list(timestamps.to_pydatetime()), settlement_points)
    cur.execute(
        "SELECT DISTINCT ON (interval_ts, settlement_point) interval_ts, settlement_point, dam_spp "
        "FROM ercot_dam_spp WHERE interval_ts = ANY(%s) AND settlement_point = ANY(%s) "
        "ORDER BY interval_ts, settlement_point, dst_flag ASC",
        params,
    )
    spp = {
        (row["interval_ts"], str(row["settlement_point"])): row["dam_spp"]
        for row in cur.fetchall()
    }
    cur.execute(
        "SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda FROM dam_system_lambda "
        "WHERE interval_ts = ANY(%s) ORDER BY interval_ts, dst_flag ASC",
        (list(timestamps.to_pydatetime()),),
    )
    lam = {row["interval_ts"]: row["system_lambda"] for row in cur.fetchall()}
    out = {sp: 0.0 for sp in settlement_points}
    complete = {sp: True for sp in settlement_points}
    for ts in timestamps.to_pydatetime():
        for sp in settlement_points:
            if spp.get((ts, sp)) is None or lam.get(ts) is None:
                complete[sp] = False
            else:
                out[sp] += float(spp[(ts, sp)]) - float(lam[ts])
    return {sp: out[sp] for sp in settlement_points if complete[sp]}


def node_market_state(
    cur, settlement_point: str, run_id: str, delivery_date, horizon: int, timestamp: datetime
) -> NodeMarketState:
    cur.execute(
        "SELECT point FROM forecast_nodal WHERE run_id = %s AND delivery_date = %s "
        "AND horizon = %s AND settlement_point = %s AND ts = %s",
        (run_id, delivery_date, horizon, settlement_point, timestamp),
    )
    forecast_row = cur.fetchone()
    forecast_congestion = (
        None if forecast_row is None or forecast_row["point"] is None else float(forecast_row["point"])
    )
    settled_by_ts = settled_system_lambdas(cur, timestamp, timestamp)
    forecast_lambda, lambda_source = forecast_system_lambda(timestamp, settled_by_ts, {})
    if forecast_congestion is not None and forecast_lambda is None:
        forecast_lambda, lambda_source = forecast_system_lambda(
            timestamp, settled_by_ts, persisted_system_lambdas_by_ct_hour(cur)
        )
    cur.execute(
        "SELECT DISTINCT ON (interval_ts, settlement_point) dam_spp FROM ercot_dam_spp "
        "WHERE interval_ts = %s AND settlement_point = %s "
        "ORDER BY interval_ts, settlement_point, dst_flag ASC",
        (timestamp, settlement_point),
    )
    dam_row = cur.fetchone()
    dam_lmp = None if dam_row is None or dam_row["dam_spp"] is None else float(dam_row["dam_spp"])
    settled_lambda = settled_by_ts.get(timestamp)
    realized_congestion = None if dam_lmp is None or settled_lambda is None else dam_lmp - settled_lambda
    return NodeMarketState(
        forecast_congestion=forecast_congestion,
        forecast_lmp=None if forecast_congestion is None or forecast_lambda is None else forecast_congestion + forecast_lambda,
        realized_congestion=realized_congestion,
        forecast_error=None if forecast_congestion is None or realized_congestion is None else forecast_congestion - realized_congestion,
        dam_lmp=dam_lmp,
        forecast_lambda_source=lambda_source,
    )


def essp_member_count(cur, settlement_point: str, timestamp: datetime) -> int | None:
    cur.execute(
        "WITH selected_group AS (SELECT group_index FROM ercot_essp WHERE interval_ts = %s "
        "AND is_study = TRUE AND settlement_point = %s LIMIT 1) "
        "SELECT count(*) AS member_count FROM ercot_essp WHERE interval_ts = %s "
        "AND is_study = TRUE AND group_index = (SELECT group_index FROM selected_group)",
        (timestamp, settlement_point, timestamp),
    )
    row = cur.fetchone()
    count = 0 if row is None else int(row["member_count"])
    return count or None
