"""Standouts panel: constraints and nodes the forecast prices unusually for
their own history, plus DAM-only surprises once the day settles.

This handler spans both domains — it imports the per-domain selectors from
``constraints`` and ``nodes`` and assembles the two row lists side by side."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import Depends, Query
import pandas as pd
from psycopg.rows import dict_row

from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (
    NodeAnalysisUnavailableResponse,
    StandoutRow,
    NodeStandoutRow,
    StandoutsAvailableResponse,
)
from compute.time import delivery_bounds
from compute.analysis.metadata import load_sp_metadata
from compute.analysis import brief_grade
from api.services.analysis.panels._common import (
    MARKET_PEAK_CT_HOURS,
    _resolve_or_unavailable,
    ranked,
    settled_history_stats,
)
from api.services.analysis.panels.constraints import (
    _standout_rows,
    _settled_standout_keys,
)
from api.services.analysis.panels.nodes import (
    _daily_node_contributions,
    _dominant_driver,
    _essp_canonical,
    _forecast_node_history,
    _node_standout_rows,
    _settled_node_history,
    _settled_node_standout_keys,
    _study_essp_groups,
)


def _history_median(values, *, absolute: bool = False) -> float | None:
    series = pd.Series(values, dtype=float)
    if absolute:
        series = series.abs()
    value = series.median()
    return None if pd.isna(value) else float(value)


def get_standouts(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    k: int = Query(4, ge=1, le=20),
) -> StandoutsAvailableResponse | NodeAnalysisUnavailableResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon
        )
        if unavailable is not None:
            return unavailable
        forecast = brief_grade.forecast_mu_profile(cur, run_id, delivery_date, horizon)
        if forecast is None:
            return NodeAnalysisUnavailableResponse(
                available=False,
                unavailable_reason="artifact_missing",
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
            )
        cur.execute(
            "SELECT constraint_key, array_agg(forecast_mu ORDER BY delivery_date) AS values "
            "FROM forecast_constraint_daily "
            "WHERE run_id = %s AND horizon = %s "
            "AND delivery_date >= %s - 30 AND delivery_date < %s "
            "GROUP BY constraint_key",
            (run_id, horizon, delivery_date, delivery_date),
        )
        histories = {
            str(row["constraint_key"]): [float(value) for value in row["values"]]
            for row in cur.fetchall()
        }
        ws, _ = delivery_bounds(delivery_date - timedelta(days=30))
        history_end, _ = delivery_bounds(delivery_date)
        cur.execute(
            "SELECT btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key, "
            "count(DISTINCT (interval_ts AT TIME ZONE 'America/Chicago')::date) AS days "
            "FROM ercot_dam_shadow_prices "
            "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
            "AND abs(shadow_price) > 0 GROUP BY constraint_name, contingency_name",
            (ws, history_end),
        )
        chronic = {
            str(row["constraint_key"]): int(row["days"]) for row in cur.fetchall()
        }
        cur.execute(
            "SELECT btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key, "
            "(interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date, "
            "sum(abs(shadow_price)) AS total "
            "FROM ercot_dam_shadow_prices "
            "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
            "GROUP BY constraint_name, contingency_name, (interval_ts AT TIME ZONE 'America/Chicago')::date "
            "ORDER BY delivery_date",
            (ws, history_end),
        )
        settled_history_by_day: dict[str, dict[date, float]] = {}
        for row in cur.fetchall():
            settled_history_by_day.setdefault(str(row["constraint_key"]), {})[
                row["delivery_date"]
            ] = float(row["total"])
        history_days = [
            delivery_date - timedelta(days=offset) for offset in range(30, 0, -1)
        ]
        settled_histories = {
            key: [values.get(day, 0.0) for day in history_days]
            for key, values in settled_history_by_day.items()
        }
        cur.execute(
            "SELECT constraint_key, zone_shares, kv_max FROM constraint_geo "
            "WHERE window_start = (SELECT max(window_start) FROM constraint_geo)"
        )
        geography = {str(row["constraint_key"]): row for row in cur.fetchall()}
        settled = brief_grade.settled_mu_profile(cur, delivery_date)
        node_result = _daily_node_contributions(
            cur, run_id, delivery_date, horizon, ct_hours=MARKET_PEAK_CT_HOURS
        )
        node_histories: dict[str, list[float]] = {}
        if node_result is not None:
            # Trailing forecast node history now reads forecast_nodal in one query
            # (0138) instead of decoding 30 prior-day artifacts; artifact fallback
            # for any absent day lives inside the helper.
            node_histories = _forecast_node_history(cur, run_id, delivery_date, horizon)
            node_settled = brief_grade.settled_node_profile(cur, delivery_date)
            node_essp_groups = _study_essp_groups(cur, node_result.hours)
        else:
            node_settled = pd.DataFrame()
            node_essp_groups = []

    forecast_total = forecast.abs().sum(axis=0)
    settled_total = (
        settled.abs().sum(axis=0) if not settled.empty else pd.Series(dtype=float)
    )
    settled_available = not settled.empty
    node_rows: list[NodeStandoutRow] = []
    if node_result is not None:
        node_terms, node_hours = node_result.terms, node_result.hours
        node_forecast_total = node_terms.sum(axis=0) / len(node_hours)
        node_settled_total = (
            node_settled.loc[
                node_settled.index.tz_convert("America/Chicago").hour.isin(
                    MARKET_PEAK_CT_HOURS
                )
            ].mean(axis=0)
            if not node_settled.empty
            else pd.Series(dtype=float)
        )
        node_rows = _node_standout_rows(
            node_forecast_total, node_histories, node_settled_total, node_terms, k=k
        )
        canonical = _essp_canonical(node_forecast_total.index, node_essp_groups)
        collapsed_rows: list[NodeStandoutRow] = []
        seen_representatives: set[str] = set()
        for row in node_rows:
            representative, count = canonical.get(
                row.settlement_point, (row.settlement_point, 1)
            )
            if representative not in seen_representatives:
                collapsed_rows.append(
                    row.model_copy(
                        update={
                            "settlement_point": representative,
                            "essp_member_count": count,
                        }
                    )
                )
                seen_representatives.add(representative)
        node_rows = collapsed_rows
        _, node_forecast_ranks = ranked(node_forecast_total.abs())
        node_settled_sorted, node_settled_ranks = ranked(node_settled_total.abs())
        forecast_points = [row.settlement_point for row in node_rows]
        settled_candidates = [
            str(point)
            for point in node_settled_sorted.index[:60]
            if str(point) not in set(forecast_points)
        ]
        history_points = forecast_points + settled_candidates
        if history_points:
            with get_pool().connection() as history_conn, history_conn.cursor(
                row_factory=dict_row
            ) as history_cur:
                node_settled_histories = _settled_node_history(
                    history_cur, delivery_date, history_points
                )
        else:
            node_settled_histories = {}
        appended_points = (
            _settled_node_standout_keys(
                node_settled_total,
                node_settled_histories,
                set(forecast_points),
                k=3,
            )
            if settled_available
            else []
        )
        metadata = load_sp_metadata(node_forecast_total.index)
        for point in appended_points:
            terms = node_terms[point] if point in node_terms else pd.Series(dtype=float)
            dominant_driver, driver_share = _dominant_driver(terms)
            node_rows.append(
                NodeStandoutRow(
                    settlement_point=point,
                    kind="settled_elevated",
                    zone=metadata.get(point, {}).get("load_zone"),
                    forecast_total=float(node_forecast_total.get(point, 0.0)),
                    forecast_history_median=_history_median(
                        node_histories.get(point, []), absolute=True
                    ),
                    forecast_history_days=len(node_histories.get(point, [])),
                    settled_total=float(node_settled_total.get(point, 0.0)),
                    dominant_driver=dominant_driver,
                    driver_share=driver_share,
                )
            )
        node_rows = [
            row.model_copy(
                update={
                    "forecast_rank": node_forecast_ranks.get(row.settlement_point),
                    "settled_rank": node_settled_ranks.get(row.settlement_point),
                    **settled_history_stats(
                        node_settled_histories[row.settlement_point],
                        nonzero_only=False,
                    ),
                }
            )
            for row in node_rows
        ]
        if settled_available:
            node_rows.sort(
                key=lambda row: (
                    row.settled_rank is None,
                    row.settled_rank if row.settled_rank is not None else float("inf"),
                    (
                        row.forecast_rank
                        if row.forecast_rank is not None
                        else float("inf")
                    ),
                )
            )
    _, forecast_ranks = ranked(forecast_total[forecast_total > 0.0])
    _, settled_ranks = ranked(settled_total[settled_total > 0.0])
    forecast_rows = _standout_rows(
        forecast_total, histories, chronic, settled_total, k=k
    )
    appended_keys = (
        _settled_standout_keys(
            settled_total,
            settled_histories,
            {row.constraint_key for row in forecast_rows},
            k=3,
        )
        if settled_available
        else []
    )
    rows: list[StandoutRow] = []
    for row in forecast_rows + [
        StandoutRow(
            constraint_key=key,
            kind="settled_elevated",
            forecast_total=float(forecast_total.get(key, 0.0)),
            forecast_history_median=_history_median(histories.get(key, [])),
            forecast_history_days=len(histories.get(key, [])),
            chronic_bound_days=chronic.get(key),
            settled_total=float(settled_total[key]),
        )
        for key in appended_keys
    ]:
        forecast_values = (
            forecast[row.constraint_key]
            if row.constraint_key in forecast
            else pd.Series(dtype=float)
        )
        settled_values = (
            settled[row.constraint_key].dropna()
            if row.constraint_key in settled
            else pd.Series(dtype=float)
        )
        geo = geography.get(row.constraint_key, {})
        shares = geo.get("zone_shares") or {}
        rows.append(
            row.model_copy(
                update={
                    "zone": max(shares, key=shares.get) if shares else None,
                    "kv_max": geo.get("kv_max"),
                    "forecast_rank": forecast_ranks.get(row.constraint_key),
                    "forecast_peak": (
                        None
                        if forecast_values.empty
                        else float(forecast_values.abs().max())
                    ),
                    "forecast_hours": int(forecast_values.ne(0.0).sum()),
                    "settled_rank": settled_ranks.get(row.constraint_key),
                    "settled_peak": (
                        None
                        if settled_values.empty
                        else float(settled_values.abs().max())
                    ),
                    "settled_hours": (
                        None if settled.empty else int(settled_values.ne(0.0).sum())
                    ),
                    **settled_history_stats(
                        settled_histories.get(row.constraint_key, [0.0] * 30),
                        nonzero_only=True,
                    ),
                }
            )
        )
    if settled_available:
        rows.sort(
            key=lambda row: (
                row.settled_rank is None,
                row.settled_rank if row.settled_rank is not None else float("inf"),
                row.forecast_rank if row.forecast_rank is not None else float("inf"),
            )
        )
    return StandoutsAvailableResponse(
        available=True,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        basis="settled" if settled_available else "forecast",
        rows=rows,
        node_rows=node_rows,
    )
