"""Node ranking: the Top Nodes table plus the node-side history, contribution,
and standout helpers shared with the standouts panel.

Node congestion is projected through each artifact's SF column; ESSP groups
collapse electrically-similar points to one representative before ranking."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import NamedTuple

from fastapi import Depends, Query
import pandas as pd
from psycopg.rows import dict_row

from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (
    NodeAnalysisUnavailableResponse,
    TopNodeRow,
    TopNodesAvailableResponse,
    NodeStandoutRow,
)
from compute.time import delivery_bounds
from compute.analysis.metadata import load_sp_metadata
from api.services.sf_artifacts import (
    load_daily_artifact,
    load_daily_artifacts,
    load_realized_mu,
)
from api.services.analysis.repositories.market import (
    settled_congestion as _settled_congestion,
)
from api.services.analysis.policy.comparison import joined_top_keys as _joined_top_keys
from api.services.analysis.panels._common import (
    MARKET_PEAK_CT_HOURS,
    MIN_STANDOUT_HISTORY_DAYS,
    NODE_CONGESTION_EPSILON,
    _resolve_or_unavailable,
    ranked,
    settled_history_stats,
)


class NodeContributions(NamedTuple):
    """Constraint × node attribution over a (possibly filtered) hour set."""

    terms: pd.DataFrame
    hours: pd.DatetimeIndex


def _dominant_driver(terms: pd.Series) -> tuple[str | None, float | None]:
    """The single constraint carrying the most of a node's congestion, and its share."""
    gross = float(terms.abs().sum())
    if gross == 0.0:
        return None, None
    return str(terms.abs().idxmax()), float(terms.abs().max() / gross)


def _study_essp_groups(cur, hours) -> list[tuple[str, ...]]:
    """Multi-node study ESSP groups that hold across every delivery hour.

    A group counts only if its exact membership appears in all ``hours`` — a
    signature that survives the whole day, not a single interval's grouping.
    """
    cur.execute(
        "SELECT interval_ts, group_index, array_agg(settlement_point ORDER BY settlement_point) AS settlement_points "
        "FROM ercot_essp WHERE interval_ts = ANY(%s) AND is_study = TRUE "
        "GROUP BY interval_ts, group_index ORDER BY interval_ts, group_index",
        (list(hours.to_pydatetime()),),
    )
    by_signature: dict[tuple[str, ...], set[datetime]] = {}
    for group in cur.fetchall():
        members = tuple(sorted(str(point) for point in group["settlement_points"]))
        if len(members) > 1:
            by_signature.setdefault(members, set()).add(group["interval_ts"])
    return [
        members
        for members, seen in by_signature.items()
        if len(seen) == len(hours)
    ]


def _essp_canonical(universe, member_groups) -> dict[str, tuple[str, int]]:
    """Map each node to its ESSP representative (min member) and group size.

    Nodes outside every multi-node group map to themselves with count 1.
    """
    canonical = {str(node): (str(node), 1) for node in universe}
    for members in member_groups:
        present = sorted(str(member) for member in members if str(member) in canonical)
        if present:
            representative = present[0]
            for member in present:
                canonical[member] = (representative, len(present))
    return canonical


def _project_node_profile(artifact, delivery_date: date) -> pd.DataFrame:
    """Project a decoded artifact's forecast μ through its SF column into a
    per-node congestion profile, clipped to D's CT day. Shared by the
    single-day path and the batched trailing-history load.

    """
    start, end = delivery_bounds(delivery_date)
    mu = artifact.E_mu.reindex(columns=artifact.SF.index, fill_value=0.0).fillna(0.0)
    profile = mu.dot(-artifact.SF)
    profile.index = pd.to_datetime(profile.index, utc=True)
    return profile.loc[(profile.index >= start) & (profile.index < end)]


def _daily_node_contributions(
    cur,
    run_id: str,
    delivery_date: date,
    horizon: int,
    *,
    realized: bool = False,
    ct_hours: tuple[int, ...] | None = None,
) -> NodeContributions | None:
    """Full-day constraint × node attribution — one artifact covers D's whole CT
    day (0133), so no cross-day stitch is needed."""
    start, end = delivery_bounds(delivery_date)
    artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        return None
    index = pd.DatetimeIndex(pd.to_datetime(artifact.E_mu.index, utc=True))
    selected = index[(index >= start) & (index < end)]
    if ct_hours is not None:
        selected = selected[selected.tz_convert("America/Chicago").hour.isin(ct_hours)]
    if not len(selected):
        return None
    mu = (
        load_realized_mu(cur, selected, artifact.SF.index)
        .reindex(artifact.SF.index)
        .fillna(0.0)
        if realized
        else artifact.E_mu.loc[selected].sum(axis=0)
    )
    terms = artifact.SF.mul(-mu, axis=0)
    return NodeContributions(terms.fillna(0.0), selected.sort_values())


def _settled_node_history(
    cur, delivery_date: date, points: list[str]
) -> dict[str, list[float]]:
    """Market-peak daily DAM congestion for a small selected node set.

    One window query grouped by (point, CT delivery day) — mirrors
    ``_settled_constraint_history``, replacing the former 30-round-trip per-day
    loop. Every requested point is present in the result (quiet days fill 0.0),
    since callers index the dict directly.

    """
    start, _ = delivery_bounds(delivery_date - timedelta(days=30))
    end, _ = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT s.settlement_point, "
        "(s.interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date, "
        "avg(s.dam_spp - l.system_lambda) AS congestion "
        "FROM ercot_dam_spp s JOIN dam_system_lambda l "
        "ON l.interval_ts = s.interval_ts AND l.dst_flag = s.dst_flag "
        "WHERE s.interval_ts >= %s AND s.interval_ts < %s "
        "AND s.settlement_point = ANY(%s) "
        "AND EXTRACT(HOUR FROM s.interval_ts AT TIME ZONE 'America/Chicago') BETWEEN 7 AND 22 "
        "AND s.dam_spp IS NOT NULL AND l.system_lambda IS NOT NULL "
        "GROUP BY s.settlement_point, (s.interval_ts AT TIME ZONE 'America/Chicago')::date",
        (start, end, points),
    )
    by_day: dict[str, dict[date, float]] = {}
    for row in cur.fetchall():
        by_day.setdefault(str(row["settlement_point"]), {})[row["delivery_date"]] = (
            float(row["congestion"])
        )
    days = [delivery_date - timedelta(days=offset) for offset in range(30, 0, -1)]
    return {
        point: [by_day.get(point, {}).get(day, 0.0) for day in days] for point in points
    }


def _forecast_node_history(
    cur, run_id: str, delivery_date: date, horizon: int
) -> dict[str, list[float]]:
    """Trailing-30-day forecast peak-hour congestion per node, read from
    ``forecast_nodal`` in one query instead of decoding 30 daily SF+μ
    artifacts.

    """
    cur.execute(
        "SELECT settlement_point, delivery_date, avg(point) AS peak_mean "
        "FROM forecast_nodal WHERE run_id = %s AND horizon = %s "
        "AND delivery_date >= %s - 30 AND delivery_date < %s AND point IS NOT NULL "
        "AND EXTRACT(HOUR FROM ts AT TIME ZONE 'America/Chicago')::int = ANY(%s) "
        "GROUP BY settlement_point, delivery_date",
        (run_id, horizon, delivery_date, delivery_date, list(MARKET_PEAK_CT_HOURS)),
    )
    histories: dict[str, list[float]] = {}
    present: set[date] = set()
    for row in cur.fetchall():
        histories.setdefault(str(row["settlement_point"]), []).append(
            float(row["peak_mean"])
        )
        present.add(row["delivery_date"])
    # Fallback: any trailing day with no forecast_nodal rows is projected the old
    # way from its artifact, so a coverage hole degrades to the prior behaviour
    # rather than silently dropping a day from every node's baseline.
    missing = [
        delivery_date - timedelta(days=offset)
        for offset in range(1, 31)
        if delivery_date - timedelta(days=offset) not in present
    ]
    if missing:
        prior_artifacts = load_daily_artifacts(cur, run_id, missing, horizon)
        for day in missing:
            artifact = prior_artifacts.get(day)
            if artifact is None:
                continue
            prior = _project_node_profile(artifact, day)
            prior_profile = prior.loc[
                prior.index.tz_convert("America/Chicago").hour.isin(
                    MARKET_PEAK_CT_HOURS
                )
            ]
            if prior_profile.empty:
                continue
            for point, value in prior_profile.mean(axis=0).items():
                histories.setdefault(str(point), []).append(float(value))
    return histories


def _node_standout_rows(
    forecast_total: pd.Series,
    histories: dict[str, list[float]],
    settled_total: pd.Series,
    forecast_terms: pd.DataFrame,
    *,
    k: int,
) -> list[NodeStandoutRow]:
    """Select nodes whose 7x16 forecast is unusually large or small for itself."""
    baseline = {
        key: float(pd.Series(values, dtype=float).abs().median())
        for key, values in histories.items()
        if len(values) >= MIN_STANDOUT_HISTORY_DAYS
        and float(pd.Series(values, dtype=float).abs().median())
        > NODE_CONGESTION_EPSILON
    }
    elevated = [
        key
        for key, median in baseline.items()
        if abs(float(forecast_total.get(key, 0.0))) / median >= 1.5
    ]
    elevated.sort(
        key=lambda key: (
            abs(float(forecast_total.get(key, 0.0))) / baseline[key],
            abs(float(forecast_total.get(key, 0.0))),
        ),
        reverse=True,
    )
    depressed = [
        key
        for key, median in baseline.items()
        if key not in elevated
        and abs(float(forecast_total.get(key, 0.0))) / median <= 0.5
    ]
    depressed.sort(
        key=lambda key: (abs(float(forecast_total.get(key, 0.0))) / baseline[key], key)
    )
    metadata = load_sp_metadata(forecast_total.index)
    rows: list[NodeStandoutRow] = []
    for key in elevated[:k] + depressed[:k]:
        terms = forecast_terms[key] if key in forecast_terms else pd.Series(dtype=float)
        dominant_driver, driver_share = _dominant_driver(terms)
        rows.append(
            NodeStandoutRow(
                settlement_point=key,
                kind=(
                    "forecast_elevated" if key in elevated[:k] else "forecast_depressed"
                ),
                zone=metadata.get(key, {}).get("load_zone"),
                forecast_total=float(forecast_total.get(key, 0.0)),
                forecast_history_median=baseline[key],
                forecast_history_days=len(histories[key]),
                settled_total=(
                    float(settled_total[key]) if key in settled_total else None
                ),
                dominant_driver=dominant_driver,
                driver_share=driver_share,
            )
        )
    return rows


def _settled_node_standout_keys(
    settled_total: pd.Series,
    histories: dict[str, list[float]],
    excluded: set[str],
    *,
    k: int,
) -> list[str]:
    """Return DAM node surprises relative to each node's own absolute history."""
    candidates: list[tuple[float, float, str]] = []
    for key, value in settled_total.items():
        key = str(key)
        historical = [
            abs(item)
            for item in histories.get(key, [])
            if abs(item) > NODE_CONGESTION_EPSILON
        ]
        if key in excluded or len(historical) < MIN_STANDOUT_HISTORY_DAYS:
            continue
        p90 = float(pd.Series(historical).quantile(0.9))
        if p90 > NODE_CONGESTION_EPSILON and abs(float(value)) / p90 >= 1.25:
            candidates.append((abs(float(value)) / p90, abs(float(value)), key))
    candidates.sort(reverse=True)
    return [key for _, _, key in candidates[:k]]


def get_top_nodes(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    k: int = Query(10, ge=1, le=15),
) -> TopNodesAvailableResponse | NodeAnalysisUnavailableResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon
        )
        if unavailable is not None:
            return unavailable
        forecast_result = _daily_node_contributions(
            cur, run_id, delivery_date, horizon, ct_hours=MARKET_PEAK_CT_HOURS
        )
        if forecast_result is None:
            return NodeAnalysisUnavailableResponse(
                available=False,
                unavailable_reason="artifact_missing",
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
            )
        forecast_terms, hours = forecast_result.terms, forecast_result.hours
        realized_result = _daily_node_contributions(
            cur,
            run_id,
            delivery_date,
            horizon,
            realized=True,
            ct_hours=MARKET_PEAK_CT_HOURS,
        )
        settled = _settled_congestion(
            cur, [str(sp) for sp in forecast_terms.columns], hours
        )
        essp_groups = _study_essp_groups(cur, hours)
        grouping = "study_delivery_day" if essp_groups else "study_essp_missing"

    forecast_total = forecast_terms.sum(axis=0)
    forecast_sorted, _ = ranked(forecast_total.abs())
    canonical = _essp_canonical(forecast_sorted.index, essp_groups)
    grouped: dict[str, tuple[float, str, int]] = {}
    for sp, value in forecast_sorted.items():
        representative, count = canonical[str(sp)]
        if representative not in grouped:
            grouped[representative] = (float(value), representative, count)
    unique_ranked = list(grouped.values())
    forecast_group_ranks = {
        sp: rank for rank, (_, sp, _) in enumerate(unique_ranked, start=1)
    }
    realized_terms = None if realized_result is None else realized_result.terms
    metadata = load_sp_metadata(forecast_terms.columns)
    settled_ranked, _ = ranked(pd.Series(settled, dtype=float).abs())
    settled_grouped: dict[str, float] = {}
    for sp in settled_ranked.index:
        representative, _ = canonical.get(str(sp), (str(sp), 1))
        settled_grouped.setdefault(representative, float(settled[str(sp)]))
    settled_unique = list(settled_grouped)
    settled_group_ranks = {sp: rank for rank, sp in enumerate(settled_unique, start=1)}
    visible_nodes = _joined_top_keys(
        pd.Index([sp for _, sp, _ in unique_ranked]),
        pd.Index(settled_unique),
        k=k,
        settled_available=bool(settled),
    )
    with get_pool().connection() as history_conn, history_conn.cursor(
        row_factory=dict_row
    ) as history_cur:
        settled_histories = _settled_node_history(
            history_cur, delivery_date, visible_nodes
        )
    group_member_counts = {sp: count for _, sp, count in unique_ranked}
    rows: list[TopNodeRow] = []
    for sp in visible_nodes:
        essp_member_count = group_member_counts.get(sp, 1)
        terms = forecast_terms[sp]
        dominant_driver, driver_share = _dominant_driver(terms)
        settled_total = settled_grouped.get(str(sp))
        realized_total = (
            None if realized_terms is None else float(realized_terms[sp].sum())
        )
        rows.append(
            TopNodeRow(
                settlement_point=str(sp),
                essp_member_count=essp_member_count,
                zone=metadata[str(sp)].get("load_zone"),
                forecast_rank=forecast_group_ranks.get(str(sp)),
                forecast_total=float(forecast_total.loc[sp] / len(hours)),
                settled_rank=settled_group_ranks.get(str(sp)),
                settled_total=(
                    None if settled_total is None else float(settled_total / len(hours))
                ),
                delta=(
                    None
                    if settled_total is None
                    else float((settled_total - forecast_total.loc[sp]) / len(hours))
                ),
                dominant_driver=dominant_driver,
                driver_share=driver_share,
                coverage=(
                    None
                    if settled_total in (None, 0.0)
                    else realized_total / settled_total
                ),
                **settled_history_stats(
                    settled_histories.get(str(sp), [0.0] * 30),
                    nonzero_only=False,
                    gate=False,
                ),
            )
        )
    return TopNodesAvailableResponse(
        available=True,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        rows=rows,
        n_ranked=len(unique_ranked),
        k=k,
        grouping=grouping,
    )
