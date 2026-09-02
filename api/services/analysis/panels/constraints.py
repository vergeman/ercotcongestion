"""Constraint ranking: the Top Constraints table plus the constraint-side
standout selectors and trailing settled-Σμ history shared with standouts/context."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import Depends, Query
import pandas as pd
from psycopg.rows import dict_row

from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (
    NodeAnalysisUnavailableResponse,
    TopConstraintRow,
    TopConstraintsAvailableResponse,
    StandoutRow,
)
from compute.time import delivery_bounds
from compute.analysis import brief_grade
from api.services.analysis.policy.comparison import joined_top_keys as _joined_top_keys
from api.services.analysis.panels._common import (
    MIN_STANDOUT_HISTORY_DAYS,
    _resolve_or_unavailable,
    ranked,
    settled_history_stats,
)


def _standout_rows(
    forecast_total: pd.Series,
    histories: dict[str, list[float]],
    chronic_bound_days: dict[str, int],
    settled_total: pd.Series,
    *,
    k: int,
) -> list[StandoutRow]:
    """Select forecast calls that are unusual relative to their own history.

    This intentionally compares forecast to forecast. DAM, if it has landed, is
    attached as evidence only; it is not smuggled into the forecast baseline.

    """
    baseline = {
        key: float(pd.Series(values, dtype=float).median())
        for key, values in histories.items()
        if len(values) >= MIN_STANDOUT_HISTORY_DAYS
        and (median := float(pd.Series(values, dtype=float).median())) > 0.0
    }
    elevated = [
        key
        for key, median in baseline.items()
        if float(forecast_total.get(key, 0.0)) > 0.0
        and float(forecast_total.get(key, 0.0)) / median >= 1.5
    ]
    elevated.sort(
        key=lambda key: (
            float(forecast_total.get(key, 0.0)) / baseline[key],
            float(forecast_total.get(key, 0.0)),
        ),
        reverse=True,
    )
    selected = elevated[:k]

    # A chronic constraint that the forecast prices unusually low is a distinct
    # useful callout. It survives even when it sat below the legacy serving floor.
    under_called = [
        key
        for key, days in chronic_bound_days.items()
        if key in baseline
        and key not in selected
        and float(forecast_total.get(key, 0.0)) <= baseline[key] * 0.25
        and days >= 24
    ]
    under_called.sort(
        key=lambda key: (
            baseline[key] - float(forecast_total.get(key, 0.0)),
            chronic_bound_days[key],
        ),
        reverse=True,
    )
    selected.extend(under_called[:k])

    rows: list[StandoutRow] = []
    for key in selected:
        rows.append(
            StandoutRow(
                constraint_key=key,
                kind=(
                    "forecast_elevated"
                    if key in elevated[:k]
                    else "chronic_under_called"
                ),
                forecast_total=float(forecast_total.get(key, 0.0)),
                forecast_history_median=baseline[key],
                forecast_history_days=len(histories[key]),
                chronic_bound_days=chronic_bound_days.get(key),
                settled_total=(
                    float(settled_total[key]) if key in settled_total else None
                ),
            )
        )
    return rows


def _settled_standout_keys(
    settled_total: pd.Series,
    histories: dict[str, list[float]],
    excluded: set[str],
    *,
    k: int,
) -> list[str]:
    """DAM-only surprises: today's Σμ materially beyond its own settled history."""
    candidates: list[tuple[float, float, str]] = []
    for key, value in settled_total.items():
        key = str(key)
        history = [item for item in histories.get(key, []) if item > 0.0]
        if key in excluded or len(history) < MIN_STANDOUT_HISTORY_DAYS or value <= 0.0:
            continue
        p90 = float(pd.Series(history).quantile(0.9))
        if p90 > 0.0 and float(value) / p90 >= 1.25:
            candidates.append((float(value) / p90, float(value), key))
    candidates.sort(reverse=True)
    return [key for _, _, key in candidates[:k]]


def _settled_constraint_history(cur, delivery_date: date) -> dict[str, list[float]]:
    """Trailing 30 Chicago delivery-day Σμ series, including quiet zero days."""
    start, _ = delivery_bounds(delivery_date - timedelta(days=30))
    end, _ = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key, "
        "(interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date, sum(abs(shadow_price)) AS total "
        "FROM ercot_dam_shadow_prices WHERE interval_ts >= %s AND interval_ts < %s "
        "AND shadow_price IS NOT NULL "
        "GROUP BY constraint_name, contingency_name, (interval_ts AT TIME ZONE 'America/Chicago')::date",
        (start, end),
    )
    by_day: dict[str, dict[date, float]] = {}
    for row in cur.fetchall():
        by_day.setdefault(str(row["constraint_key"]), {})[row["delivery_date"]] = float(
            row["total"]
        )
    days = [delivery_date - timedelta(days=offset) for offset in range(30, 0, -1)]
    return {
        key: [values.get(day, 0.0) for day in days] for key, values in by_day.items()
    }


def get_top_constraints(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    k: int = Query(10, ge=1, le=15),
) -> TopConstraintsAvailableResponse | NodeAnalysisUnavailableResponse:
    """Rank the complete artifact vocabulary; do not reuse the legacy brief cast."""
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
        settled = brief_grade.settled_mu_profile(cur, delivery_date)
        settled_histories = _settled_constraint_history(cur, delivery_date)

        cur.execute(
            "SELECT constraint_key, zone_shares, kv_max FROM constraint_geo "
            "WHERE window_start = (SELECT max(window_start) FROM constraint_geo)"
        )
        geography = {str(row["constraint_key"]): row for row in cur.fetchall()}

    forecast_mass = forecast.abs().sum(axis=0)
    ranked_mass, forecast_ranks = ranked(forecast_mass[forecast_mass > 0.0])
    settled_mass = (
        settled.abs().sum(axis=0) if not settled.empty else pd.Series(dtype=float)
    )
    settled_ranked, settled_ranks = ranked(settled_mass[settled_mass > 0.0])
    visible_keys = _joined_top_keys(
        ranked_mass.index,
        settled_ranked.index,
        k=k,
        settled_available=not settled.empty,
    )
    rows: list[TopConstraintRow] = []
    for key in visible_keys:
        forecast_values = (
            forecast[key] if key in forecast else pd.Series(0.0, index=forecast.index)
        )
        settled_values = settled[key].dropna() if key in settled else None
        geo = geography.get(str(key), {})
        shares = geo.get("zone_shares") or {}
        rows.append(
            TopConstraintRow(
                constraint_key=str(key),
                forecast_rank=forecast_ranks.get(str(key)),
                forecast_total=float(forecast_mass.get(key, 0.0)),
                forecast_peak=float(forecast_values.abs().max()),
                forecast_hours=int(forecast_values.ne(0.0).sum()),
                zone=max(shares, key=shares.get) if shares else None,
                kv_max=geo.get("kv_max"),
                settled_rank=settled_ranks.get(str(key)),
                settled_total=(
                    None
                    if settled_values is None
                    else float(settled_values.abs().sum())
                ),
                settled_peak=(
                    None
                    if settled_values is None or settled_values.empty
                    else float(settled_values.abs().max())
                ),
                settled_hours=(
                    None
                    if settled_values is None
                    else int(settled_values.ne(0.0).sum())
                ),
                **settled_history_stats(
                    settled_histories.get(str(key), [0.0] * 30), nonzero_only=True
                ),
            )
        )
    return TopConstraintsAvailableResponse(
        available=True,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        rows=rows,
        n_ranked=len(ranked_mass),
        k=k,
    )
