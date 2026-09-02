"""Context panel: the Brief's closing structural rollups — congestion by voltage
class and the chronic-element list — served ready-made, no browser aggregation."""

from __future__ import annotations

from datetime import date

from fastapi import Depends, Query
import pandas as pd
from psycopg.rows import dict_row

from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (
    VoltageClassRow,
    ChronicElementRow,
    ContextAvailableResponse,
    ContextUnavailableResponse,
)
from compute.analysis import brief_grade
from api.services.analysis.panels._common import _resolve_or_unavailable
from api.services.analysis.panels.constraints import _settled_constraint_history


def _voltage_class(kv_max: float | None) -> str:
    """Use the persisted maximum element voltage; keep unknown geography explicit."""
    if kv_max is None:
        return "Unknown"
    return f"{int(round(float(kv_max)))} kV"


def get_context(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    chronic_limit: int = Query(14, ge=1, le=50),
) -> ContextAvailableResponse | ContextUnavailableResponse:
    """Serve the Brief's closing structural context without browser rollups."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon, ContextUnavailableResponse
        )
        if unavailable is not None:
            return unavailable
        forecast = brief_grade.forecast_mu_profile(cur, run_id, delivery_date, horizon)
        if forecast is None:
            return ContextUnavailableResponse(
                available=False,
                unavailable_reason="artifact_missing",
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
            )
        settled = brief_grade.settled_mu_profile(cur, delivery_date)
        histories = _settled_constraint_history(cur, delivery_date)
        cur.execute(
            "SELECT constraint_key, kv_max FROM constraint_geo "
            "WHERE window_start = (SELECT max(window_start) FROM constraint_geo)"
        )
        voltage_by_key = {
            str(row["constraint_key"]): row["kv_max"] for row in cur.fetchall()
        }

    profile = settled if not settled.empty else forecast
    basis = "settled" if not settled.empty else "forecast"
    totals = profile.abs().sum(axis=0)
    total_mu = float(totals.sum())
    classes: dict[str, dict[str, float | int]] = {}
    for key, total in totals.items():
        if float(total) <= 0.0:
            continue
        label = _voltage_class(voltage_by_key.get(str(key)))
        values = profile[key].dropna()
        bucket = classes.setdefault(
            label, {"constraint_keys": 0, "binding_hours": 0, "mu": 0.0}
        )
        bucket["constraint_keys"] = int(bucket["constraint_keys"]) + 1
        bucket["binding_hours"] = int(bucket["binding_hours"]) + int(
            values.ne(0.0).sum()
        )
        bucket["mu"] = float(bucket["mu"]) + float(total)

    def voltage_sort(item: tuple[str, dict[str, float | int]]) -> tuple[int, float]:
        label, bucket = item
        number = float(label.split()[0]) if label != "Unknown" else -1.0
        return (label != "Unknown", number)

    voltage_classes = []
    for label, bucket in sorted(classes.items(), key=voltage_sort, reverse=True):
        hours = int(bucket["binding_hours"])
        mass = float(bucket["mu"])
        voltage_classes.append(
            VoltageClassRow(
                voltage_class=label,
                constraint_keys=int(bucket["constraint_keys"]),
                binding_hours=hours,
                average_mu=mass / hours if hours else 0.0,
                share_of_mu=mass / total_mu if total_mu else 0.0,
            )
        )

    chronic = []
    for key, values in histories.items():
        days_bound = sum(value > 0.0 for value in values)
        if days_bound < 24:
            continue
        constraint, contingency = key.split("|", 1)
        # Median over binding days only, matching the Top Constraints whisker's
        # nonzero-day p50 (both read the same trailing series) so one element
        # shows a single "median Σμ" everywhere on the Brief.
        nonzero = [value for value in values if value > 0.0]
        chronic.append(
            ChronicElementRow(
                element=constraint,
                contingency=contingency,
                days_bound=days_bound,
                usual_total=float(pd.Series(nonzero, dtype=float).median()),
            )
        )
    chronic.sort(key=lambda row: row.usual_total, reverse=True)
    return ContextAvailableResponse(
        available=True,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        basis=basis,
        voltage_classes=voltage_classes,
        chronic_elements=chronic[:chronic_limit],
    )
