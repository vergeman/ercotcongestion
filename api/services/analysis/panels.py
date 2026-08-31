"""Query-backed endpoints for the daily Brief's analysis panels."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from time import perf_counter
from typing import Literal, NamedTuple

from fastapi import Depends, HTTPException, Query
import pandas as pd
from psycopg.rows import dict_row, tuple_row

from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (AnalysisContributionTerm, NodeMarketState, GradeAvailableResponse,
                    GradeHalfResponse, GradeUnavailableResponse, HeroAvailableResponse,
                    HeroLatestResponse, HeroUnavailableAtHorizonResponse, HeroUnavailableResponse,
                    NodeAnalysisAvailableResponse, NodeAnalysisUnavailableResponse,
                    AnalysisSettlementPointsAvailableResponse,
                    AnalysisSettlementPointsUnavailableResponse,
                    AnalysisConstraintsAvailableResponse,
                    AnalysisConstraintsUnavailableResponse, ForecastMuAvailableResponse,
                    ForecastMuUnavailableResponse, EsspGroup,
                    AnalysisEsspGroupsAvailableResponse, AnalysisEsspGroupsUnavailableResponse,
                    TopConstraintRow, TopConstraintsAvailableResponse,
                    TopConstraintsUnavailableResponse, TopNodeRow,
                    TopNodesAvailableResponse, TopNodesUnavailableResponse,
                    StandoutRow, NodeStandoutRow, StandoutsAvailableResponse, StandoutsUnavailableResponse,
                    VoltageClassRow, ChronicElementRow, ContextAvailableResponse,
                    ContextUnavailableResponse, GradeHistoryHalfResponse,
                    GradeHistoryDayResponse, GradeHistoryAvailableResponse,
                    GradeHistoryUnavailableResponse)
from compute.analysis.hero import magnitude_verdict
from compute.analysis.hero_builder import build_hero
from compute.analysis.hero_window import delivery_bounds
from compute.analysis.phrases import phrase_for, render
from compute.analysis.metadata import load_sp_metadata
from compute.analysis.brief_grade import (
    COMPARISONS as _BRIEF_COMPARISONS,
    grade_constraint_profiles as _brief_grade_constraint_profiles,
    grade_node_profiles as _brief_grade_node_profiles,
    serialize_grade_half as _serialize_brief_grade_half,
)
from compute.projection.codecs import node_contributions
from api.services.sf_artifacts import load_daily_artifact, load_daily_artifacts, load_realized_mu
from api.services.system_lambda import (
    forecast_system_lambda,
    persisted_system_lambdas_by_ct_hour,
    settled_system_lambdas,
)
from api.services.analysis.resolution import (
    dam_landed as _dam_landed,
    resolve_delivery_date as _resolve_brief_delivery_date,
    resolve_horizon as _resolve_horizon,
    resolve_run as _resolve_run,
    selected_hours as _selected_hours,
)
from api.services.analysis.queries import (
    constraints_response,
    essp_groups_response,
    forecast_mu_response,
    node_response,
    settlement_points_response,
)

logger = logging.getLogger(__name__)

# Emit a single composition breakdown only when an uncached Brief request is
# visibly slow. This is intentionally a request-level diagnostic rather than
# per-SQL logging: it identifies the section worth taking to EXPLAIN without
# adding a high-volume production log stream.
_BRIEF_SLOW_REQUEST_SECONDS = 1.0


def _iso_z(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _cursor(delivery_date: date, artifact) -> dict[str, str]:
    """Delivery-day bounds plus the artifact's largest forecast-μ hour."""
    ws, we = delivery_bounds(delivery_date)
    peak = artifact.E_mu.abs().sum(axis=1).idxmax()
    return {"ws": _iso_z(ws), "we": _iso_z(we), "t": _iso_z(peak)}


def _settled_congestion(cur, settlement_points: list[str], timestamps: pd.DatetimeIndex) -> dict[str, float]:
    params = (list(timestamps.to_pydatetime()), settlement_points)
    cur.execute(
        "SELECT DISTINCT ON (interval_ts, settlement_point) interval_ts, settlement_point, dam_spp "
        "FROM ercot_dam_spp WHERE interval_ts = ANY(%s) AND settlement_point = ANY(%s) "
        "ORDER BY interval_ts, settlement_point, dst_flag ASC", params)
    spp = {(row["interval_ts"], str(row["settlement_point"])): row["dam_spp"] for row in cur.fetchall()}
    cur.execute(
        "SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda FROM dam_system_lambda "
        "WHERE interval_ts = ANY(%s) ORDER BY interval_ts, dst_flag ASC",
        (list(timestamps.to_pydatetime()),))
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


def _node_market_state(cur, settlement_point: str, run_id: str, delivery_date: date,
                       horizon: int, timestamp: datetime) -> NodeMarketState:
    """One node's Map-equivalent congestion/LMP values at the Detail cursor."""
    cur.execute(
        """
        SELECT point FROM forecast_nodal
        WHERE run_id = %s AND delivery_date = %s AND horizon = %s
          AND settlement_point = %s AND ts = %s
        """,
        (run_id, delivery_date, horizon, settlement_point, timestamp),
    )
    forecast_row = cur.fetchone()
    forecast_congestion = (
        None if forecast_row is None or forecast_row["point"] is None
        else float(forecast_row["point"])
    )

    settled_by_ts = settled_system_lambdas(cur, timestamp, timestamp)
    forecast_lambda, lambda_source = forecast_system_lambda(timestamp, settled_by_ts, {})
    if forecast_congestion is not None and forecast_lambda is None:
        persisted = persisted_system_lambdas_by_ct_hour(cur)
        forecast_lambda, lambda_source = forecast_system_lambda(timestamp, settled_by_ts, persisted)

    cur.execute(
        """
        SELECT DISTINCT ON (interval_ts, settlement_point) dam_spp
        FROM ercot_dam_spp
        WHERE interval_ts = %s AND settlement_point = %s
        ORDER BY interval_ts, settlement_point, dst_flag ASC
        """,
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


def _essp_member_count(cur, settlement_point: str, timestamp: datetime) -> int | None:
    """Return the selected node's study-vintage ESSP group size, if present."""
    cur.execute(
        """
        WITH selected_group AS (
            SELECT group_index
            FROM ercot_essp
            WHERE interval_ts = %s AND is_study = TRUE AND settlement_point = %s
            LIMIT 1
        )
        SELECT count(*) AS member_count
        FROM ercot_essp
        WHERE interval_ts = %s AND is_study = TRUE
          AND group_index = (SELECT group_index FROM selected_group)
        """,
        (timestamp, settlement_point, timestamp),
    )
    row = cur.fetchone()
    count = 0 if row is None else int(row["member_count"])
    return count or None


def _constraint_geo(cur, keys: list[str]) -> dict[str, dict]:
    """Best-effort ctype/zone/kv_max per key; absent geography is null, never
    an error. Mirrors ``matrix.py::_constraint_types``'s per-key latest-window
    lookup, extended with the zone/kv_max fields ``/analysis/top-constraints``
    already derives the same way (max zone_shares mass)."""
    if not keys:
        return {}
    cur.execute(
        "SELECT DISTINCT ON (constraint_key) constraint_key, ctype, zone_shares, kv_max "
        "FROM constraint_geo WHERE constraint_key = ANY(%s) "
        "ORDER BY constraint_key, window_start DESC",
        (keys,),
    )
    result: dict[str, dict] = {}
    for row in cur.fetchall():
        shares = row["zone_shares"] or {}
        result[str(row["constraint_key"])] = {
            "ctype": row["ctype"],
            "zone": max(shares, key=shares.get) if shares else None,
            "kv_max": row["kv_max"],
        }
    return result


def _terms(contributions: pd.Series, shift_factors: pd.Series) -> list[AnalysisContributionTerm]:
    contributions = contributions[contributions != 0.0]
    ordered = contributions.reindex(contributions.abs().sort_values(ascending=False).index)
    return [AnalysisContributionTerm(constraint_key=str(key), contribution=float(value),
                                    shift_factor=float(shift_factors.loc[key]))
            for key, value in ordered.items()]


def _structural_terms(shift_factors: pd.Series, contributions: pd.Series) -> list[AnalysisContributionTerm]:
    """Every nonzero SF relationship, including constraints quiet this hour."""
    sf = shift_factors[shift_factors != 0.0]
    ordered = sf.reindex(sf.abs().sort_values(ascending=False).index)
    return [AnalysisContributionTerm(
        constraint_key=str(key), contribution=float(contributions.loc[key]),
        shift_factor=float(value),
    ) for key, value in ordered.items()]


def _verdicts(forecast: dict, settled: dict) -> dict[str, dict | None]:
    """Grade slots independently; condition data has no actual counterpart."""
    return {
        "magnitude": magnitude_verdict(forecast["magnitude"], settled["magnitude"]),
        "regime": None,
        "where": {"bucket": "held" if forecast["where"].get("zone") == settled["where"].get("zone")
                  else "shifted"},
        "exceptions": {"bucket": "held" if forecast["exceptions"].get("bucket")
                       == settled["exceptions"].get("bucket") else "shifted"},
    }


def _settled_mu_profile(cur, delivery_date: date) -> pd.DataFrame:
    """Hourly DAM μ with absent rows preserved as NaN and published $0 intact."""
    start, end = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT DISTINCT ON (interval_ts, constraint_name, contingency_name) "
        "interval_ts, btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key, "
        "shadow_price FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
        "ORDER BY interval_ts, constraint_name, contingency_name, dst_flag ASC",
        (start, end),
    )
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    frame = pd.DataFrame(rows)
    frame["interval_ts"] = pd.to_datetime(frame["interval_ts"], utc=True)
    # pivot, rather than a group-by sum, deliberately retains a numeric zero as
    # an ERCOT binding label and leaves an absent row as NaN.
    return frame.pivot(index="interval_ts", columns="constraint_key", values="shadow_price").sort_index()


def _joined_top_keys(
    forecast_keys: pd.Index,
    settled_keys: pd.Index,
    *,
    k: int,
    settled_available: bool,
) -> list[str]:
    """Return the visible ranking for one Brief phase.

    Before settlement the brief is simply the forecast top-k.  After settlement,
    DAM owns the leading order and the forecast top-k survivors are appended as
    comparison rows.  This deliberately produces up to 2k rows: a missed DAM
    leader must not displace a forecast leader that readers need to inspect.
    """
    forecast_top = [str(key) for key in forecast_keys[:k]]
    if not settled_available:
        return forecast_top
    settled_top = [str(key) for key in settled_keys[:k]]
    settled_set = set(settled_top)
    return settled_top + [key for key in forecast_top if key not in settled_set]


def _standout_rows(
    forecast_total: pd.Series,
    histories: dict[str, list[float]],
    chronic_bound_days: dict[str, int],
    settled_total: pd.Series,
    *,
    k: int,
) -> list[StandoutRow]:
    """Select forecast calls that are unusual relative to their own history.

    This intentionally compares forecast to forecast.  DAM, if it has landed,
    is attached as evidence only; it is not smuggled into the forecast baseline.
    """
    baseline = {
        key: float(pd.Series(values, dtype=float).median())
        for key, values in histories.items()
        if len(values) >= MIN_STANDOUT_HISTORY_DAYS and (median := float(pd.Series(values, dtype=float).median())) > 0.0
    }
    elevated = [
        key for key, median in baseline.items()
        if float(forecast_total.get(key, 0.0)) > 0.0 and float(forecast_total.get(key, 0.0)) / median >= 1.5
    ]
    elevated.sort(key=lambda key: (float(forecast_total.get(key, 0.0)) / baseline[key],
                                   float(forecast_total.get(key, 0.0))), reverse=True)
    selected = elevated[:k]

    # A chronic constraint that the forecast prices unusually low is a distinct
    # useful callout. It survives even when it sat below the legacy serving floor.
    under_called = [
        key for key, days in chronic_bound_days.items()
        if key in baseline and key not in selected
        and float(forecast_total.get(key, 0.0)) <= baseline[key] * 0.25
        and days >= 24
    ]
    under_called.sort(key=lambda key: (baseline[key] - float(forecast_total.get(key, 0.0)),
                                       chronic_bound_days[key]), reverse=True)
    selected.extend(under_called[:k])

    rows: list[StandoutRow] = []
    for key in selected:
        rows.append(StandoutRow(
            constraint_key=key,
            kind="forecast_elevated" if key in elevated[:k] else "chronic_under_called",
            forecast_total=float(forecast_total.get(key, 0.0)),
            forecast_history_median=baseline[key],
            forecast_history_days=len(histories[key]),
            chronic_bound_days=chronic_bound_days.get(key),
            settled_total=(float(settled_total[key]) if key in settled_total else None),
        ))
    return rows


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
        if len(values) >= MIN_STANDOUT_HISTORY_DAYS and float(pd.Series(values, dtype=float).abs().median()) > NODE_CONGESTION_EPSILON
    }
    elevated = [
        key for key, median in baseline.items()
        if abs(float(forecast_total.get(key, 0.0))) / median >= 1.5
    ]
    elevated.sort(key=lambda key: (abs(float(forecast_total.get(key, 0.0))) / baseline[key],
                                   abs(float(forecast_total.get(key, 0.0)))), reverse=True)
    depressed = [
        key for key, median in baseline.items()
        if key not in elevated and abs(float(forecast_total.get(key, 0.0))) / median <= 0.5
    ]
    depressed.sort(key=lambda key: (abs(float(forecast_total.get(key, 0.0))) / baseline[key], key))
    metadata = load_sp_metadata(forecast_total.index)
    rows: list[NodeStandoutRow] = []
    for key in elevated[:k] + depressed[:k]:
        terms = forecast_terms[key] if key in forecast_terms else pd.Series(dtype=float)
        gross = float(terms.abs().sum())
        rows.append(NodeStandoutRow(
            settlement_point=key,
            kind="forecast_elevated" if key in elevated[:k] else "forecast_depressed",
            zone=metadata.get(key, {}).get("load_zone"),
            forecast_total=float(forecast_total.get(key, 0.0)),
            forecast_history_median=baseline[key],
            forecast_history_days=len(histories[key]),
            settled_total=(float(settled_total[key]) if key in settled_total else None),
            dominant_driver=None if gross == 0.0 else str(terms.abs().idxmax()),
            driver_share=None if gross == 0.0 else float(terms.abs().max() / gross),
        ))
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


def _settled_node_history(cur, delivery_date: date, points: list[str]) -> dict[str, list[float]]:
    """Market-peak daily DAM congestion for a small selected node set.

    One window query grouped by (point, CT delivery day) — mirrors
    ``_settled_constraint_history``, replacing the former 30-round-trip
    per-day loop (0137). Every requested point is present in the result
    (quiet days fill 0.0), since callers index the dict directly."""
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
        by_day.setdefault(str(row["settlement_point"]), {})[row["delivery_date"]] = float(row["congestion"])
    days = [delivery_date - timedelta(days=offset) for offset in range(30, 0, -1)]
    return {point: [by_day.get(point, {}).get(day, 0.0) for day in days] for point in points}


def _forecast_node_history(cur, run_id: str, delivery_date: date,
                           horizon: int) -> dict[str, list[float]]:
    """Trailing-30-day forecast peak-hour congestion per node, read from
    ``forecast_nodal`` in one query instead of decoding 30 daily SF+μ artifacts
    (0138).

    ``forecast_nodal.point`` is the same ``−(E[μ]·SF)`` the artifact path projects
    (``compute/sf/project.py``), so this is numerically equivalent to the old
    ``_project_node_profile`` loop within the table's float32 storage. Grouping on
    the stored ``delivery_date`` label (not the CT date of ``ts``) reproduces the
    artifact path's per-day binning exactly — including for days still on the
    pre-0133 UTC-day cut — while the ``MARKET_PEAK_CT_HOURS`` filter matches the CT
    7×16 window the loop applied.

    Any prior day absent from ``forecast_nodal`` falls back to decoding that day's
    artifact (belt-and-suspenders: prod nodal coverage tracks the artifacts in
    lockstep, since ``persist_forecast`` writes both atomically). Values are
    one-per-present-day and unordered; the standout selectors consume only each
    series' length and median."""
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
        histories.setdefault(str(row["settlement_point"]), []).append(float(row["peak_mean"]))
        present.add(row["delivery_date"])
    # Fallback: any trailing day with no forecast_nodal rows is projected the old
    # way from its artifact, so a coverage hole degrades to the prior behaviour
    # rather than silently dropping a day from every node's baseline.
    missing = [delivery_date - timedelta(days=offset) for offset in range(1, 31)
               if delivery_date - timedelta(days=offset) not in present]
    if missing:
        prior_artifacts = load_daily_artifacts(cur, run_id, missing, horizon)
        for day in missing:
            artifact = prior_artifacts.get(day)
            if artifact is None:
                continue
            prior = _project_node_profile(artifact, day)
            prior_profile = prior.loc[
                prior.index.tz_convert("America/Chicago").hour.isin(MARKET_PEAK_CT_HOURS)]
            if prior_profile.empty:
                continue
            for point, value in prior_profile.mean(axis=0).items():
                histories.setdefault(str(point), []).append(float(value))
    return histories


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
        by_day.setdefault(str(row["constraint_key"]), {})[row["delivery_date"]] = float(row["total"])
    days = [delivery_date - timedelta(days=offset) for offset in range(30, 0, -1)]
    return {key: [values.get(day, 0.0) for day in days] for key, values in by_day.items()}


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
        historical = [abs(item) for item in histories.get(key, []) if abs(item) > NODE_CONGESTION_EPSILON]
        if key in excluded or len(historical) < MIN_STANDOUT_HISTORY_DAYS:
            continue
        p90 = float(pd.Series(historical).quantile(0.9))
        if p90 > NODE_CONGESTION_EPSILON and abs(float(value)) / p90 >= 1.25:
            candidates.append((abs(float(value)) / p90, abs(float(value)), key))
    candidates.sort(reverse=True)
    return [key for _, _, key in candidates[:k]]


class NodeContributions(NamedTuple):
    """Constraint × node attribution over a (possibly filtered) hour set."""
    terms: pd.DataFrame
    hours: pd.DatetimeIndex


def _forecast_mu_profile(cur, run_id: str, delivery_date: date, horizon: int) -> pd.DataFrame | None:
    """D's forecast μ profile over its CT day — one artifact covers it whole (0133)."""
    start, end = delivery_bounds(delivery_date)
    artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        return None
    profile = artifact.E_mu.copy()
    profile.index = pd.to_datetime(profile.index, utc=True)
    return profile.loc[(profile.index >= start) & (profile.index < end)]


def _project_node_profile(artifact, delivery_date: date) -> pd.DataFrame:
    """Project a decoded artifact's forecast μ through its SF column into a
    per-node congestion profile, clipped to D's CT day. Shared by the single-day
    path and the batched trailing-history load (0137)."""
    start, end = delivery_bounds(delivery_date)
    mu = artifact.E_mu.reindex(columns=artifact.SF.index, fill_value=0.0).fillna(0.0)
    profile = mu.dot(-artifact.SF)
    profile.index = pd.to_datetime(profile.index, utc=True)
    return profile.loc[(profile.index >= start) & (profile.index < end)]


def _forecast_node_profile(cur, run_id: str, delivery_date: date, horizon: int) -> pd.DataFrame | None:
    """Project D's forecast μ hours through the day's complete SF column."""
    artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
    return None if artifact is None else _project_node_profile(artifact, delivery_date)


def _daily_node_contributions(cur, run_id: str, delivery_date: date, horizon: int,
                              *, realized: bool = False,
                              ct_hours: tuple[int, ...] | None = None) -> NodeContributions | None:
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
    mu = (load_realized_mu(cur, selected, artifact.SF.index).reindex(artifact.SF.index).fillna(0.0)
          if realized else artifact.E_mu.loc[selected].sum(axis=0))
    terms = artifact.SF.mul(-mu, axis=0)
    return NodeContributions(terms.fillna(0.0), selected.sort_values())


def _settled_node_profile(cur, delivery_date: date) -> pd.DataFrame:
    """Published hourly SPP-minus-λ congestion, retaining a numeric $0 row."""
    start, end = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT DISTINCT ON (s.interval_ts, s.settlement_point) "
        "s.interval_ts, s.settlement_point, s.dam_spp - l.system_lambda AS congestion "
        "FROM ercot_dam_spp s JOIN dam_system_lambda l "
        "ON l.interval_ts = s.interval_ts AND l.dst_flag = s.dst_flag "
        "WHERE s.interval_ts >= %s AND s.interval_ts < %s "
        "AND s.dam_spp IS NOT NULL AND l.system_lambda IS NOT NULL "
        "ORDER BY s.interval_ts, s.settlement_point, s.dst_flag ASC",
        (start, end),
    )
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    frame = pd.DataFrame(rows)
    frame["interval_ts"] = pd.to_datetime(frame["interval_ts"], utc=True)
    return frame.pivot(index="interval_ts", columns="settlement_point", values="congestion").sort_index()


def _ordinal_profile(profile: pd.DataFrame, count: int) -> pd.DataFrame:
    """Put a prior delivery day's hourly values onto the target's lag-24 grid."""
    result = profile.copy()
    result.index = pd.RangeIndex(len(result))
    return result.reindex(pd.RangeIndex(count))


def _windowed_mu_profiles(cur, delivery_date: date, days: int) -> dict[date, pd.DataFrame]:
    """Batched trailing-window counterpart to ``_settled_mu_profile``: one query
    over the whole window, split by CT delivery day, instead of one round trip
    per day (0137) — ``_trailing_settled_average``'s dominant cost.

    Fetches via a plain ``tuple_row`` cursor rather than the request's shared
    ``dict_row`` one: a wide trailing window is tens of thousands of rows, and
    building one dict per row (vs. a tuple) measurably dominates fetch time at
    that volume (0137 profiling: ~30% faster fetch+frame-construction)."""
    window_start, _ = delivery_bounds(delivery_date - timedelta(days=days))
    _, window_end = delivery_bounds(delivery_date - timedelta(days=1))
    with cur.connection.cursor(row_factory=tuple_row) as bulk_cur:
        bulk_cur.execute(
            "SELECT DISTINCT ON (interval_ts, constraint_name, contingency_name) "
            "interval_ts, btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key, "
            "shadow_price FROM ercot_dam_shadow_prices "
            "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
            "ORDER BY interval_ts, constraint_name, contingency_name, dst_flag ASC",
            (window_start, window_end),
        )
        rows = bulk_cur.fetchall()
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["interval_ts", "constraint_key", "shadow_price"])
    frame["interval_ts"] = pd.to_datetime(frame["interval_ts"], utc=True)
    frame["delivery_date"] = frame["interval_ts"].dt.tz_convert("America/Chicago").dt.date
    return {
        day: day_frame.pivot(index="interval_ts", columns="constraint_key",
                             values="shadow_price").sort_index()
        for day, day_frame in frame.groupby("delivery_date")
    }


def _windowed_node_profiles(cur, delivery_date: date, days: int) -> dict[date, pd.DataFrame]:
    """Batched trailing-window counterpart to ``_settled_node_profile`` — see
    ``_windowed_mu_profiles`` (including why this uses a ``tuple_row`` cursor)."""
    window_start, _ = delivery_bounds(delivery_date - timedelta(days=days))
    _, window_end = delivery_bounds(delivery_date - timedelta(days=1))
    with cur.connection.cursor(row_factory=tuple_row) as bulk_cur:
        bulk_cur.execute(
            "SELECT DISTINCT ON (s.interval_ts, s.settlement_point) "
            "s.interval_ts, s.settlement_point, s.dam_spp - l.system_lambda AS congestion "
            "FROM ercot_dam_spp s JOIN dam_system_lambda l "
            "ON l.interval_ts = s.interval_ts AND l.dst_flag = s.dst_flag "
            "WHERE s.interval_ts >= %s AND s.interval_ts < %s "
            "AND s.dam_spp IS NOT NULL AND l.system_lambda IS NOT NULL "
            "ORDER BY s.interval_ts, s.settlement_point, s.dst_flag ASC",
            (window_start, window_end),
        )
        rows = bulk_cur.fetchall()
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["interval_ts", "settlement_point", "congestion"])
    frame["interval_ts"] = pd.to_datetime(frame["interval_ts"], utc=True)
    frame["delivery_date"] = frame["interval_ts"].dt.tz_convert("America/Chicago").dt.date
    return {
        day: day_frame.pivot(index="interval_ts", columns="settlement_point",
                             values="congestion").sort_index()
        for day, day_frame in frame.groupby("delivery_date")
    }


def _trailing_settled_average(delivery_date: date, count: int,
                              by_day: dict[date, pd.DataFrame]) -> pd.DataFrame | None:
    """A complete trailing-30-day settled baseline on the target's ordinal hours.

    ``by_day`` is pre-fetched by ``_windowed_mu_profiles``/``_windowed_node_profiles``
    (one query for the whole window) rather than looked up one query per day."""
    profiles = []
    for offset in range(1, 31):
        profile = by_day.get(delivery_date - timedelta(days=offset))
        if profile is None or profile.empty:
            return None
        profiles.append(_ordinal_profile(profile, count))
    universe = list(dict.fromkeys(str(key) for profile in profiles for key in profile.columns))
    if not universe:
        return None
    return sum((profile.reindex(index=pd.RangeIndex(count), columns=universe, fill_value=0.0)
                .fillna(0.0) for profile in profiles)) / len(profiles)


def _grade_vocabulary(cur, delivery_date: date) -> list[str]:
    """Every key that settled in the prototype's trailing 30-day universe."""
    start, end = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT DISTINCT btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key "
        "FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
        "ORDER BY constraint_key",
        (start - timedelta(days=30), end),
    )
    return [str(row["constraint_key"]) for row in cur.fetchall()]


NODE_CONGESTION_EPSILON = 1e-6  # $/MWh; suppresses float residue, not economics.
MARKET_PEAK_CT_HOURS = tuple(range(7, 23))  # 7×16, every delivery day.
# Minimum trailing days an element needs before its history yields a trustworthy
# standout baseline.  Unrelated to the top-k row cap — this gates eligibility,
# not row count.
MIN_STANDOUT_HISTORY_DAYS = 10


def get_node(
    settlement_point: str = Query(..., min_length=1),
    delivery_date: date = Query(...),
    basis: str = Query("predicted", pattern="^(predicted|realized)$"),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    hours: list[datetime] | None = Query(None),
    min_abs_sf: float = Query(0.0, ge=0.0),
    mode: Literal["drivers", "structural"] = Query("drivers"),
    include_detail: bool = Query(False, description="Include Matrix Detail's structural terms and ESSP count."),
) -> NodeAnalysisAvailableResponse | NodeAnalysisUnavailableResponse:
    """Decompose a node from every represented constraint, never a brief top-k."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return NodeAnalysisUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return NodeAnalysisUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date, horizon=horizon,
            )
        return node_response(
            cur=cur, artifact=artifact, settlement_point=settlement_point, run_id=run_id,
            delivery_date=delivery_date, horizon=horizon, basis=basis, hours=hours,
            min_abs_sf=min_abs_sf, mode=mode, include_detail=include_detail,
            selected_hours=_selected_hours, settled_congestion=_settled_congestion,
            node_market_state=_node_market_state, essp_member_count=_essp_member_count,
            terms=_terms, structural_terms=_structural_terms,
        )


def get_settlement_points(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
) -> AnalysisSettlementPointsAvailableResponse | AnalysisSettlementPointsUnavailableResponse:
    """List all artifact columns once for counterparty discovery, never a Matrix screen."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return AnalysisSettlementPointsUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return AnalysisSettlementPointsUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date, horizon=horizon,
            )
    return settlement_points_response(
        artifact=artifact, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
        metadata_loader=load_sp_metadata,
    )


def get_constraints(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
) -> AnalysisConstraintsAvailableResponse | AnalysisConstraintsUnavailableResponse:
    """List every constraint in one day's artifact for search, ranked by
    Σ|E_mu| — the full universe, never a Brief top-k."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return AnalysisConstraintsUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return AnalysisConstraintsUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date, horizon=horizon,
            )
        keys = [str(key) for key in artifact.E_mu.columns]
        geography = _constraint_geo(cur, keys)

    return constraints_response(
        artifact=artifact, geography=geography, run_id=run_id,
        delivery_date=delivery_date, horizon=horizon,
    )


def get_essp_groups(
    interval_ts: datetime = Query(...),
    source: str = Query("study", pattern="^(study|final)$"),
) -> AnalysisEsspGroupsAvailableResponse | AnalysisEsspGroupsUnavailableResponse:
    """Return raw ESSP membership for one hour and vintage.

    The caller chooses the hour used by its view (the v6 brief uses its peak
    hour) and deliberately chooses the causal study or post-DAM final.  No
    cross-day fallback is applied: membership is hourly topology data, not a
    static node attribute.
    """
    if interval_ts.tzinfo is None:
        raise HTTPException(status_code=422, detail="interval_ts must include a UTC offset.")
    interval_ts = pd.Timestamp(interval_ts).tz_convert("UTC").to_pydatetime()
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT group_index, array_agg(settlement_point ORDER BY settlement_point) AS settlement_points "
            "FROM ercot_essp WHERE interval_ts = %s AND is_study = %s "
            "GROUP BY group_index ORDER BY group_index",
            (interval_ts, source == "study"),
        )
        rows = cur.fetchall()
    return essp_groups_response(rows=rows, interval_ts=interval_ts, source=source)


def get_grade(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
) -> GradeAvailableResponse | GradeUnavailableResponse:
    """Score constraints without blending them with the separately exposed node half."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return GradeUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        # An unsettled delivery day has no DAM μ to grade against.  Report both
        # halves as settlement-pending rather than a real-looking zero score:
        # the grade scorer would otherwise return magnitude_overlap 0.0 with
        # null APs, and a materialization run before DAM lands would persist it.
        if _settled_mu_profile(cur, delivery_date).empty:
            pending = GradeHalfResponse(graded=False, unavailable_reason="settlement_pending")
            return GradeAvailableResponse(
                available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
                constraints=pending, nodes=pending,
            )
        cur.execute(
            "SELECT subject, detail FROM analysis_grade_daily "
            "WHERE run_id = %s AND delivery_date = %s AND horizon = %s AND detail IS NOT NULL",
            (run_id, delivery_date, horizon),
        )
        materialized = {str(row["subject"]): row["detail"] for row in cur.fetchall()}
        if "constraints" in materialized and "nodes" in materialized:
            return GradeAvailableResponse(
                available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
                constraints=GradeHalfResponse(**_brief_payload(materialized["constraints"])),
                nodes=GradeHalfResponse(**_brief_payload(materialized["nodes"])),
            )
        constraints = _brief_grade_constraint_profiles(cur, run_id, delivery_date, horizon)
        nodes = _brief_grade_node_profiles(cur, run_id, delivery_date, horizon)
    if constraints is None:
        return GradeUnavailableResponse(
            available=False, unavailable_reason="artifact_missing", run_id=run_id,
            delivery_date=delivery_date, horizon=horizon,
        )
    return GradeAvailableResponse(
        available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
        constraints=GradeHalfResponse(**_brief_payload(_serialize_brief_grade_half(constraints))),
        nodes=(GradeHalfResponse(**_brief_payload(_serialize_brief_grade_half(nodes))) if nodes is not None else
               GradeHalfResponse(graded=False, unavailable_reason="node_data_missing")),
    )


def _brief_payload(payload: dict) -> dict:
    """Enrich a pre-0189 materialized Brief grade without changing its legacy keys."""
    if payload.get("comparisons"):
        return payload
    result = dict(payload)
    available = [comparison for comparison in _BRIEF_COMPARISONS
                 if result.get(comparison.result_field) is not None]
    result["comparisons"] = [
        {"id": comparison.id, "label": comparison.label, "definition": comparison.definition}
        for comparison in available
    ]
    result["comparison_metrics"] = [
        {"id": comparison.id, "metrics": result[comparison.result_field]}
        for comparison in available
    ]
    return result


def get_grade_history(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    days: int = Query(30, ge=1, le=30),
) -> GradeHistoryAvailableResponse | GradeHistoryUnavailableResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return GradeHistoryUnavailableResponse(available=False, unavailable_reason="artifact_missing",
                                                   run_id=run_id, delivery_date=delivery_date)
        cur.execute(
            "SELECT delivery_date, subject, model, persistence FROM analysis_grade_daily "
            "WHERE run_id = %s AND horizon = %s AND delivery_date >= %s - %s "
            "AND delivery_date < %s ORDER BY delivery_date, subject",
            (run_id, horizon, delivery_date, days, delivery_date),
        )
        grouped: dict[date, dict[str, dict]] = {}
        for row in cur.fetchall():
            grouped.setdefault(row["delivery_date"], {})[str(row["subject"])] = {
                "model": row["model"], "persistence": row["persistence"],
            }
    descriptors = [
        {"id": comparison.id, "label": comparison.label, "definition": comparison.definition}
        for comparison in _BRIEF_COMPARISONS
    ]
    result = [GradeHistoryDayResponse(
        delivery_date=day,
        constraints=GradeHistoryHalfResponse(
            **values["constraints"], comparisons=descriptors,
            comparison_metrics=[
                {"id": _BRIEF_COMPARISONS[0].id, "metrics": values["constraints"]["model"]},
                {"id": _BRIEF_COMPARISONS[1].id, "metrics": values["constraints"]["persistence"]},
            ],
        ),
        nodes=GradeHistoryHalfResponse(
            **values["nodes"], comparisons=descriptors,
            comparison_metrics=[
                {"id": _BRIEF_COMPARISONS[0].id, "metrics": values["nodes"]["model"]},
                {"id": _BRIEF_COMPARISONS[1].id, "metrics": values["nodes"]["persistence"]},
            ],
        ),
    ) for day, values in grouped.items()
              if "constraints" in values and "nodes" in values]
    return GradeHistoryAvailableResponse(available=True, run_id=run_id, delivery_date=delivery_date,
                                         horizon=horizon, days=result)


def get_forecast_mu(
    constraint_key: list[str] = Query(..., min_length=1,
                                      description="One or more canonical constraint|contingency keys."),
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
) -> ForecastMuAvailableResponse | ForecastMuUnavailableResponse:
    """Serve a narrow, untruncated E_mu slice without altering the model fit."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return ForecastMuUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return ForecastMuUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date, horizon=horizon,
            )

    return forecast_mu_response(
        artifact=artifact, constraint_keys=constraint_key, run_id=run_id,
        delivery_date=delivery_date, horizon=horizon,
    )


def get_top_constraints(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    k: int = Query(10, ge=1, le=15),
) -> TopConstraintsAvailableResponse | TopConstraintsUnavailableResponse:
    """Rank the complete artifact vocabulary; do not reuse the legacy brief cast."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return TopConstraintsUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        forecast = _forecast_mu_profile(cur, run_id, delivery_date, horizon)
        if forecast is None:
            return TopConstraintsUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date, horizon=horizon,
            )
        settled = _settled_mu_profile(cur, delivery_date)
        settled_histories = _settled_constraint_history(cur, delivery_date)

        cur.execute(
            "SELECT constraint_key, zone_shares, kv_max FROM constraint_geo "
            "WHERE window_start = (SELECT max(window_start) FROM constraint_geo)"
        )
        geography = {str(row["constraint_key"]): row for row in cur.fetchall()}

    forecast_mass = forecast.abs().sum(axis=0)
    ranked = forecast_mass[forecast_mass > 0.0].sort_values(ascending=False, kind="stable")
    settled_mass = settled.abs().sum(axis=0) if not settled.empty else pd.Series(dtype=float)
    settled_ranked = settled_mass[settled_mass > 0.0].sort_values(ascending=False, kind="stable")
    forecast_ranks = {str(key): rank for rank, key in enumerate(ranked.index, start=1)}
    settled_ranks = {str(key): rank for rank, key in enumerate(settled_ranked.index, start=1)}
    visible_keys = _joined_top_keys(
        ranked.index, settled_ranked.index, k=k, settled_available=not settled.empty,
    )
    rows: list[TopConstraintRow] = []
    for key in visible_keys:
        forecast_values = forecast[key] if key in forecast else pd.Series(0.0, index=forecast.index)
        settled_values = settled[key].dropna() if key in settled else None
        geo = geography.get(str(key), {})
        shares = geo.get("zone_shares") or {}
        historical = settled_histories.get(str(key), [0.0] * 30)
        nonzero_historical = [value for value in historical if value > 0.0]
        rows.append(TopConstraintRow(
            constraint_key=str(key), forecast_rank=forecast_ranks.get(str(key)),
            forecast_total=float(forecast_mass.get(key, 0.0)),
            forecast_peak=float(forecast_values.abs().max()),
            forecast_hours=int(forecast_values.ne(0.0).sum()),
            zone=max(shares, key=shares.get) if shares else None,
            kv_max=geo.get("kv_max"),
            settled_rank=settled_ranks.get(str(key)),
            settled_total=(None if settled_values is None else float(settled_values.abs().sum())),
            settled_peak=(None if settled_values is None or settled_values.empty
                          else float(settled_values.abs().max())),
            settled_hours=(None if settled_values is None else int(settled_values.ne(0.0).sum())),
            settled_history_p10=(None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.1))),
            settled_history_p25=(None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.25))),
            settled_history_p50=(None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.5))),
            settled_history_p75=(None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.75))),
            settled_history_p90=(None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.9))),
            settled_history=historical,
        ))
    return TopConstraintsAvailableResponse(
        available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
        rows=rows, n_ranked=len(ranked), k=k,
    )


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
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return ContextUnavailableResponse(available=False, unavailable_reason="artifact_missing",
                                              run_id=run_id, delivery_date=delivery_date)
        forecast = _forecast_mu_profile(cur, run_id, delivery_date, horizon)
        if forecast is None:
            return ContextUnavailableResponse(available=False, unavailable_reason="artifact_missing",
                                              run_id=run_id, delivery_date=delivery_date, horizon=horizon)
        settled = _settled_mu_profile(cur, delivery_date)
        histories = _settled_constraint_history(cur, delivery_date)
        cur.execute(
            "SELECT constraint_key, kv_max FROM constraint_geo "
            "WHERE window_start = (SELECT max(window_start) FROM constraint_geo)"
        )
        voltage_by_key = {str(row["constraint_key"]): row["kv_max"] for row in cur.fetchall()}

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
        bucket = classes.setdefault(label, {"constraint_keys": 0, "binding_hours": 0, "mu": 0.0})
        bucket["constraint_keys"] = int(bucket["constraint_keys"]) + 1
        bucket["binding_hours"] = int(bucket["binding_hours"]) + int(values.ne(0.0).sum())
        bucket["mu"] = float(bucket["mu"]) + float(total)

    def voltage_sort(item: tuple[str, dict[str, float | int]]) -> tuple[int, float]:
        label, bucket = item
        number = float(label.split()[0]) if label != "Unknown" else -1.0
        return (label != "Unknown", number)

    voltage_classes = []
    for label, bucket in sorted(classes.items(), key=voltage_sort, reverse=True):
        hours = int(bucket["binding_hours"])
        mass = float(bucket["mu"])
        voltage_classes.append(VoltageClassRow(
            voltage_class=label,
            constraint_keys=int(bucket["constraint_keys"]),
            binding_hours=hours,
            average_mu=mass / hours if hours else 0.0,
            share_of_mu=mass / total_mu if total_mu else 0.0,
        ))

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
        chronic.append(ChronicElementRow(
            element=constraint, contingency=contingency, days_bound=days_bound,
            usual_total=float(pd.Series(nonzero, dtype=float).median()),
        ))
    chronic.sort(key=lambda row: row.usual_total, reverse=True)
    return ContextAvailableResponse(
        available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon, basis=basis,
        voltage_classes=voltage_classes, chronic_elements=chronic[:chronic_limit],
    )


def get_standouts(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    k: int = Query(4, ge=1, le=20),
) -> StandoutsAvailableResponse | StandoutsUnavailableResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return StandoutsUnavailableResponse(available=False, unavailable_reason="artifact_missing",
                                                run_id=run_id, delivery_date=delivery_date)
        forecast = _forecast_mu_profile(cur, run_id, delivery_date, horizon)
        if forecast is None:
            return StandoutsUnavailableResponse(available=False, unavailable_reason="artifact_missing",
                                                run_id=run_id, delivery_date=delivery_date, horizon=horizon)
        cur.execute(
            "SELECT constraint_key, array_agg(forecast_mu ORDER BY delivery_date) AS values "
            "FROM forecast_constraint_daily "
            "WHERE run_id = %s AND horizon = %s "
            "AND delivery_date >= %s - 30 AND delivery_date < %s "
            "GROUP BY constraint_key",
            (run_id, horizon, delivery_date, delivery_date),
        )
        histories = {str(row["constraint_key"]): [float(value) for value in row["values"]]
                     for row in cur.fetchall()}
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
        chronic = {str(row["constraint_key"]): int(row["days"]) for row in cur.fetchall()}
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
            settled_history_by_day.setdefault(str(row["constraint_key"]), {})[row["delivery_date"]] = float(row["total"])
        history_days = [delivery_date - timedelta(days=offset) for offset in range(30, 0, -1)]
        settled_histories = {
            key: [values.get(day, 0.0) for day in history_days]
            for key, values in settled_history_by_day.items()
        }
        cur.execute(
            "SELECT constraint_key, zone_shares, kv_max FROM constraint_geo "
            "WHERE window_start = (SELECT max(window_start) FROM constraint_geo)"
        )
        geography = {str(row["constraint_key"]): row for row in cur.fetchall()}
        settled = _settled_mu_profile(cur, delivery_date)
        node_result = _daily_node_contributions(
            cur, run_id, delivery_date, horizon, ct_hours=MARKET_PEAK_CT_HOURS)
        node_histories: dict[str, list[float]] = {}
        if node_result is not None:
            # Trailing forecast node history now reads forecast_nodal in one query
            # (0138) instead of decoding 30 prior-day artifacts; artifact fallback
            # for any absent day lives inside the helper.
            node_histories = _forecast_node_history(cur, run_id, delivery_date, horizon)
            node_settled = _settled_node_profile(cur, delivery_date)
            cur.execute(
                "SELECT interval_ts, array_agg(settlement_point ORDER BY settlement_point) AS settlement_points "
                "FROM ercot_essp WHERE interval_ts = ANY(%s) AND is_study = TRUE "
                "GROUP BY interval_ts, group_index ORDER BY interval_ts, group_index",
                (list(node_result.hours.to_pydatetime()),),
            )
            essp_by_signature: dict[tuple[str, ...], set[datetime]] = {}
            for group in cur.fetchall():
                members = tuple(sorted(str(point) for point in group["settlement_points"]))
                if len(members) > 1:
                    essp_by_signature.setdefault(members, set()).add(group["interval_ts"])
            node_essp_groups = [members for members, seen in essp_by_signature.items()
                                if len(seen) == len(node_result.hours)]
        else:
            node_settled = pd.DataFrame()
            node_essp_groups = []

    forecast_total = forecast.abs().sum(axis=0)
    settled_total = settled.abs().sum(axis=0) if not settled.empty else pd.Series(dtype=float)
    settled_available = not settled.empty
    node_rows: list[NodeStandoutRow] = []
    if node_result is not None:
        node_terms, node_hours = node_result.terms, node_result.hours
        node_forecast_total = node_terms.sum(axis=0) / len(node_hours)
        node_settled_total = (node_settled.loc[
            node_settled.index.tz_convert("America/Chicago").hour.isin(MARKET_PEAK_CT_HOURS)
        ].mean(axis=0) if not node_settled.empty else pd.Series(dtype=float))
        node_rows = _node_standout_rows(node_forecast_total, node_histories, node_settled_total,
                                        node_terms, k=k)
        canonical = {str(point): (str(point), 1) for point in node_forecast_total.index}
        for members in node_essp_groups:
            present = [point for point in members if point in canonical]
            if present:
                representative = present[0]
                for point in present:
                    canonical[point] = (representative, len(present))
        collapsed_rows: list[NodeStandoutRow] = []
        seen_representatives: set[str] = set()
        for row in node_rows:
            representative, count = canonical.get(row.settlement_point, (row.settlement_point, 1))
            if representative not in seen_representatives:
                collapsed_rows.append(row.model_copy(update={
                    "settlement_point": representative, "essp_member_count": count,
                }))
                seen_representatives.add(representative)
        node_rows = collapsed_rows
        node_forecast_ranks = {str(key): rank for rank, key in enumerate(
            node_forecast_total.abs().sort_values(ascending=False, kind="stable").index, start=1)}
        node_settled_ranks = {str(key): rank for rank, key in enumerate(
            node_settled_total.abs().sort_values(ascending=False, kind="stable").index, start=1)}
        forecast_points = [row.settlement_point for row in node_rows]
        settled_candidates = [str(point) for point in node_settled_total.abs().sort_values(
            ascending=False, kind="stable").index[:60] if str(point) not in set(forecast_points)]
        history_points = forecast_points + settled_candidates
        if history_points:
            with get_pool().connection() as history_conn, history_conn.cursor(row_factory=dict_row) as history_cur:
                node_settled_histories = _settled_node_history(history_cur, delivery_date, history_points)
        else:
            node_settled_histories = {}
        appended_points = _settled_node_standout_keys(
            node_settled_total, node_settled_histories, set(forecast_points), k=3,
        ) if settled_available else []
        metadata = load_sp_metadata(node_forecast_total.index)
        for point in appended_points:
            terms = node_terms[point] if point in node_terms else pd.Series(dtype=float)
            gross = float(terms.abs().sum())
            node_rows.append(NodeStandoutRow(
                settlement_point=point, kind="settled_elevated",
                zone=metadata.get(point, {}).get("load_zone"),
                forecast_total=float(node_forecast_total.get(point, 0.0)),
                forecast_history_median=float(pd.Series(node_histories.get(point, [])).abs().median()),
                forecast_history_days=len(node_histories.get(point, [])),
                settled_total=float(node_settled_total.get(point, 0.0)),
                dominant_driver=None if gross == 0.0 else str(terms.abs().idxmax()),
                driver_share=None if gross == 0.0 else float(terms.abs().max() / gross),
            ))
        node_rows = [row.model_copy(update={
            "forecast_rank": node_forecast_ranks.get(row.settlement_point),
            "settled_rank": node_settled_ranks.get(row.settlement_point),
            "settled_history_p10": (None if not any(abs(value) > NODE_CONGESTION_EPSILON for value in node_settled_histories[row.settlement_point])
                                    else float(pd.Series(node_settled_histories[row.settlement_point]).quantile(0.1))),
            "settled_history_p25": (None if not any(abs(value) > NODE_CONGESTION_EPSILON for value in node_settled_histories[row.settlement_point]) else float(pd.Series(node_settled_histories[row.settlement_point]).quantile(0.25))),
            "settled_history_p50": (None if not any(abs(value) > NODE_CONGESTION_EPSILON for value in node_settled_histories[row.settlement_point]) else float(pd.Series(node_settled_histories[row.settlement_point]).quantile(0.5))),
            "settled_history_p75": (None if not any(abs(value) > NODE_CONGESTION_EPSILON for value in node_settled_histories[row.settlement_point]) else float(pd.Series(node_settled_histories[row.settlement_point]).quantile(0.75))),
            "settled_history_p90": (None if not any(abs(value) > NODE_CONGESTION_EPSILON for value in node_settled_histories[row.settlement_point])
                                    else float(pd.Series(node_settled_histories[row.settlement_point]).quantile(0.9))),
            "settled_history": node_settled_histories[row.settlement_point],
        }) for row in node_rows]
        if settled_available:
            node_rows.sort(key=lambda row: (
                row.settled_rank is None, row.settled_rank if row.settled_rank is not None else float("inf"),
                row.forecast_rank if row.forecast_rank is not None else float("inf"),
            ))
    forecast_ranked = forecast_total[forecast_total > 0.0].sort_values(ascending=False, kind="stable")
    settled_ranked = settled_total[settled_total > 0.0].sort_values(ascending=False, kind="stable")
    forecast_ranks = {str(key): rank for rank, key in enumerate(forecast_ranked.index, start=1)}
    settled_ranks = {str(key): rank for rank, key in enumerate(settled_ranked.index, start=1)}
    forecast_rows = _standout_rows(forecast_total, histories, chronic, settled_total, k=k)
    appended_keys = _settled_standout_keys(
        settled_total, settled_histories, {row.constraint_key for row in forecast_rows}, k=3,
    ) if settled_available else []
    rows: list[StandoutRow] = []
    for row in forecast_rows + [StandoutRow(
        constraint_key=key, kind="settled_elevated", forecast_total=float(forecast_total.get(key, 0.0)),
        forecast_history_median=float(pd.Series(histories.get(key, [])).median()),
        forecast_history_days=len(histories.get(key, [])), chronic_bound_days=chronic.get(key),
        settled_total=float(settled_total[key]),
    ) for key in appended_keys]:
        forecast_values = forecast[row.constraint_key] if row.constraint_key in forecast else pd.Series(dtype=float)
        settled_values = settled[row.constraint_key].dropna() if row.constraint_key in settled else pd.Series(dtype=float)
        historical = settled_histories.get(row.constraint_key, [0.0] * 30)
        nonzero_historical = [value for value in historical if value > 0.0]
        geo = geography.get(row.constraint_key, {})
        shares = geo.get("zone_shares") or {}
        rows.append(row.model_copy(update={
            "zone": max(shares, key=shares.get) if shares else None,
            "kv_max": geo.get("kv_max"),
            "forecast_rank": forecast_ranks.get(row.constraint_key),
            "forecast_peak": None if forecast_values.empty else float(forecast_values.abs().max()),
            "forecast_hours": int(forecast_values.ne(0.0).sum()),
            "settled_rank": settled_ranks.get(row.constraint_key),
            "settled_peak": None if settled_values.empty else float(settled_values.abs().max()),
            "settled_hours": None if settled.empty else int(settled_values.ne(0.0).sum()),
            "settled_history_p10": None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.1)),
            "settled_history_p25": None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.25)),
            "settled_history_p50": None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.5)),
            "settled_history_p75": None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.75)),
            "settled_history_p90": None if not nonzero_historical else float(pd.Series(nonzero_historical).quantile(0.9)),
            "settled_history": historical,
        }))
    if settled_available:
        rows.sort(key=lambda row: (
            row.settled_rank is None, row.settled_rank if row.settled_rank is not None else float("inf"),
            row.forecast_rank if row.forecast_rank is not None else float("inf"),
        ))
    return StandoutsAvailableResponse(
        available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
        basis="settled" if settled_available else "forecast",
        rows=rows,
        node_rows=node_rows,
    )


def get_top_nodes(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    k: int = Query(10, ge=1, le=15),
) -> TopNodesAvailableResponse | TopNodesUnavailableResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return TopNodesUnavailableResponse(available=False, unavailable_reason="artifact_missing",
                                               run_id=run_id, delivery_date=delivery_date)
        forecast_result = _daily_node_contributions(
            cur, run_id, delivery_date, horizon, ct_hours=MARKET_PEAK_CT_HOURS)
        if forecast_result is None:
            return TopNodesUnavailableResponse(available=False, unavailable_reason="artifact_missing",
                                               run_id=run_id, delivery_date=delivery_date, horizon=horizon)
        forecast_terms, hours = forecast_result.terms, forecast_result.hours
        realized_result = _daily_node_contributions(
            cur, run_id, delivery_date, horizon, realized=True, ct_hours=MARKET_PEAK_CT_HOURS)
        settled = _settled_congestion(cur, [str(sp) for sp in forecast_terms.columns], hours)
        essp_groups: list[dict] = []
        grouping = "study_essp_missing"
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
        essp_groups = [{"settlement_points": members} for members, seen in by_signature.items()
                       if len(seen) == len(hours)]
        if essp_groups:
            grouping = "study_delivery_day"

    forecast_total = forecast_terms.sum(axis=0)
    ranked = forecast_total.abs().sort_values(ascending=False, kind="stable")
    canonical: dict[str, tuple[str, int]] = {str(sp): (str(sp), 1) for sp in ranked.index}
    for group in essp_groups:
        members = sorted(str(sp) for sp in group["settlement_points"] if str(sp) in canonical)
        if members:
            representative = members[0]
            for member in members:
                canonical[member] = (representative, len(members))
    grouped: dict[str, tuple[float, str, int]] = {}
    for sp, value in ranked.items():
        representative, count = canonical[str(sp)]
        if representative not in grouped:
            grouped[representative] = (float(value), representative, count)
    unique_ranked = list(grouped.values())
    forecast_group_ranks = {sp: rank for rank, (_, sp, _) in enumerate(unique_ranked, start=1)}
    realized_terms = None if realized_result is None else realized_result.terms
    metadata = load_sp_metadata(forecast_terms.columns)
    settled_ranked = pd.Series(settled, dtype=float).abs().sort_values(ascending=False, kind="stable")
    settled_grouped: dict[str, float] = {}
    for sp in settled_ranked.index:
        representative, _ = canonical.get(str(sp), (str(sp), 1))
        settled_grouped.setdefault(representative, float(settled[str(sp)]))
    settled_unique = list(settled_grouped)
    settled_group_ranks = {sp: rank for rank, sp in enumerate(settled_unique, start=1)}
    visible_nodes = _joined_top_keys(
        pd.Index([sp for _, sp, _ in unique_ranked]), pd.Index(settled_unique),
        k=k, settled_available=bool(settled),
    )
    with get_pool().connection() as history_conn, history_conn.cursor(row_factory=dict_row) as history_cur:
        settled_histories = _settled_node_history(history_cur, delivery_date, visible_nodes)
    group_member_counts = {sp: count for _, sp, count in unique_ranked}
    rows: list[TopNodeRow] = []
    for sp in visible_nodes:
        essp_member_count = group_member_counts.get(sp, 1)
        terms = forecast_terms[sp]
        gross = float(terms.abs().sum())
        settled_total = settled_grouped.get(str(sp))
        realized_total = None if realized_terms is None else float(realized_terms[sp].sum())
        historical = settled_histories.get(str(sp), [0.0] * 30)
        history_series = pd.Series(historical)
        rows.append(TopNodeRow(
            settlement_point=str(sp), essp_member_count=essp_member_count,
            zone=metadata[str(sp)].get("load_zone"),
            forecast_rank=forecast_group_ranks.get(str(sp)), forecast_total=float(forecast_total.loc[sp] / len(hours)),
            settled_rank=settled_group_ranks.get(str(sp)),
            settled_total=None if settled_total is None else float(settled_total / len(hours)),
            delta=None if settled_total is None else float((settled_total - forecast_total.loc[sp]) / len(hours)),
            dominant_driver=None if gross == 0.0 else str(terms.abs().idxmax()),
            driver_share=None if gross == 0.0 else float(terms.abs().max() / gross),
            coverage=(None if settled_total in (None, 0.0) else realized_total / settled_total),
            settled_history_p10=float(history_series.quantile(0.1)),
            settled_history_p25=float(history_series.quantile(0.25)),
            settled_history_p50=float(history_series.quantile(0.5)),
            settled_history_p75=float(history_series.quantile(0.75)),
            settled_history_p90=float(history_series.quantile(0.9)),
            settled_history=historical,
        ))
    return TopNodesAvailableResponse(available=True, run_id=run_id, delivery_date=delivery_date,
                                     horizon=horizon, rows=rows, n_ranked=len(unique_ranked), k=k,
                                     grouping=grouping)


def get_hero_latest(
    run_id: str | None = Depends(_server_selected_run),
) -> HeroLatestResponse:
    """Discover a cold-entry day from the artifacts required by Brief tables.

    One artifact now covers its whole CT delivery day (0133), so the newest
    published day just needs its own artifact — no following day required.
    """
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        cur.execute(
            "SELECT delivery_date, horizon FROM forecast_sf_artifact "
            "WHERE run_id = %s "
            "ORDER BY delivery_date DESC, horizon ASC LIMIT 1",
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        return HeroLatestResponse(available=False, run_id=run_id)
    return HeroLatestResponse(
        available=True, run_id=run_id, delivery_date=row["delivery_date"], horizon=int(row["horizon"]),
    )


def get_hero(
    delivery_date: date | None = Query(None, description="ERCOT delivery day."),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2, description="Artifact track; final preferred."),
    *,
    date_: date | None = Query(None, alias="date", deprecated=True,
                               description="Deprecated alias for delivery_date."),
    include_condition: bool = True,
) -> HeroAvailableResponse | HeroUnavailableResponse | HeroUnavailableAtHorizonResponse:
    """Return prose segments, raw slots, independent verdicts, and map cursor."""
    delivery_date = _resolve_brief_delivery_date(delivery_date, date_)
    started = perf_counter()
    artifact_elapsed = 0.0
    builder_elapsed = 0.0
    # All window reads below share this checked-out connection.  Do not release
    # it before ``build_hero``: it performs the on-demand query layer itself.
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if run_id is None:
                cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=503, detail="no forecast run is published yet.")
                run_id = str(row["run_id"])
            if horizon is None:
                cur.execute(
                    "SELECT min(horizon) AS h FROM forecast_sf_artifact "
                    "WHERE run_id = %s AND delivery_date = %s", (run_id, delivery_date))
                row = cur.fetchone()
                if row is None or row["h"] is None:
                    return {"available": False, "unavailable_reason": "artifact_missing",
                            "run_id": run_id, "delivery_date": delivery_date}
                horizon = int(row["h"])
            artifact_started = perf_counter()
            artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
            artifact_elapsed = perf_counter() - artifact_started
            settled = _dam_landed(cur, delivery_date)

        if artifact is None:
            return {"available": False, "unavailable_reason": "artifact_missing", "run_id": run_id,
                    "delivery_date": delivery_date, "horizon": horizon}
        basis = "settled" if settled else "forecast"
        builder_started = perf_counter()
        slots = build_hero(
            conn, run_id, delivery_date, horizon, basis, artifact=artifact,
            include_condition=include_condition,
        )
        builder_elapsed = perf_counter() - builder_started
        verdict = None
        if settled:
            forecast = build_hero(
                conn, run_id, delivery_date, horizon, "forecast", artifact=artifact,
                include_condition=include_condition,
            )
            verdict = _verdicts(forecast, slots)
        response = {
            "available": True,
            "segments": render(slots),
            "slots": slots,
            "verdict": verdict,
            "cursor": _cursor(delivery_date, artifact),
            "provenance": {"run_id": run_id, "delivery_date": delivery_date,
                           "horizon": horizon, "basis": basis},
        }
        elapsed = perf_counter() - started
        if elapsed >= _BRIEF_SLOW_REQUEST_SECONDS:
            logger.info(
                "hero_request_profile day=%s run=%s horizon=%s basis=%s condition=%s total=%.3fs "
                "artifact=%.3fs builder=%.3fs",
                delivery_date, run_id, horizon, basis, elapsed,
                include_condition, artifact_elapsed, builder_elapsed,
            )
        return response
