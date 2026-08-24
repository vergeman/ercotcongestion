"""Database-backed inputs and neutral serialization for Brief grades.

This module deliberately depends only on the compute/runtime import boundary.
The API turns its neutral dictionaries into response models; scheduled jobs can
materialize exactly the same result without importing the API application.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from psycopg.rows import tuple_row

from compute.analysis.grade import GradeResult, grade_profiles
from compute.analysis.hero_window import delivery_bounds
from compute.sf.project import load_sf_mu


NODE_CONGESTION_EPSILON = 1e-6


def _load_daily_artifact(cur, run_id: str, delivery_date: date, horizon: int):
    cur.execute(
        "SELECT sf_npz FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
        (run_id, delivery_date, horizon),
    )
    row = cur.fetchone()
    return None if row is None else load_sf_mu(bytes(row["sf_npz"]))


def settled_mu_profile(cur, delivery_date: date) -> pd.DataFrame:
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
    return frame.pivot(index="interval_ts", columns="constraint_key", values="shadow_price").sort_index()


def forecast_mu_profile(cur, run_id: str, delivery_date: date, horizon: int) -> pd.DataFrame | None:
    start, end = delivery_bounds(delivery_date)
    artifact = _load_daily_artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        return None
    profile = artifact.E_mu.copy()
    profile.index = pd.to_datetime(profile.index, utc=True)
    return profile.loc[(profile.index >= start) & (profile.index < end)]


def _forecast_node_profile(cur, run_id: str, delivery_date: date, horizon: int) -> pd.DataFrame | None:
    artifact = _load_daily_artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        return None
    start, end = delivery_bounds(delivery_date)
    mu = artifact.E_mu.reindex(columns=artifact.SF.index, fill_value=0.0).fillna(0.0)
    profile = mu.dot(-artifact.SF)
    profile.index = pd.to_datetime(profile.index, utc=True)
    return profile.loc[(profile.index >= start) & (profile.index < end)]


def _settled_node_profile(cur, delivery_date: date) -> pd.DataFrame:
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
    result = profile.copy()
    result.index = pd.RangeIndex(len(result))
    return result.reindex(pd.RangeIndex(count))


def _windowed_profiles(cur, delivery_date: date, days: int, *, nodes: bool) -> dict[date, pd.DataFrame]:
    window_start, _ = delivery_bounds(delivery_date - timedelta(days=days))
    _, window_end = delivery_bounds(delivery_date - timedelta(days=1))
    if nodes:
        sql = (
            "SELECT DISTINCT ON (s.interval_ts, s.settlement_point) "
            "s.interval_ts, s.settlement_point, s.dam_spp - l.system_lambda AS value "
            "FROM ercot_dam_spp s JOIN dam_system_lambda l "
            "ON l.interval_ts = s.interval_ts AND l.dst_flag = s.dst_flag "
            "WHERE s.interval_ts >= %s AND s.interval_ts < %s "
            "AND s.dam_spp IS NOT NULL AND l.system_lambda IS NOT NULL "
            "ORDER BY s.interval_ts, s.settlement_point, s.dst_flag ASC"
        )
        key = "settlement_point"
    else:
        sql = (
            "SELECT DISTINCT ON (interval_ts, constraint_name, contingency_name) "
            "interval_ts, btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key, "
            "shadow_price AS value FROM ercot_dam_shadow_prices "
            "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
            "ORDER BY interval_ts, constraint_name, contingency_name, dst_flag ASC"
        )
        key = "constraint_key"
    with cur.connection.cursor(row_factory=tuple_row) as bulk_cur:
        bulk_cur.execute(sql, (window_start, window_end))
        rows = bulk_cur.fetchall()
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["interval_ts", key, "value"])
    frame["interval_ts"] = pd.to_datetime(frame["interval_ts"], utc=True)
    frame["delivery_date"] = frame["interval_ts"].dt.tz_convert("America/Chicago").dt.date
    return {day: group.pivot(index="interval_ts", columns=key, values="value").sort_index()
            for day, group in frame.groupby("delivery_date")}


def _trailing_settled_average(delivery_date: date, count: int,
                              by_day: dict[date, pd.DataFrame]) -> pd.DataFrame | None:
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
    start, end = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT DISTINCT btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key "
        "FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
        "ORDER BY constraint_key",
        (start - timedelta(days=30), end),
    )
    return [str(row["constraint_key"]) for row in cur.fetchall()]


def grade_constraint_profiles(cur, run_id: str, delivery_date: date,
                              horizon: int) -> GradeResult | None:
    profile = forecast_mu_profile(cur, run_id, delivery_date, horizon)
    if profile is None:
        return None
    settled = settled_mu_profile(cur, delivery_date)
    persistence = settled_mu_profile(cur, delivery_date - timedelta(days=1))
    model = _ordinal_profile(profile, len(profile))
    settled = _ordinal_profile(settled, len(profile))
    persistence = _ordinal_profile(persistence, len(profile))
    climatology = _trailing_settled_average(delivery_date, len(profile),
                                             _windowed_profiles(cur, delivery_date, 30, nodes=False))
    return grade_profiles(model, settled, persistence, settled_bound=settled.notna(),
                          climatology=climatology, universe=_grade_vocabulary(cur, delivery_date))


def grade_node_profiles(cur, run_id: str, delivery_date: date,
                        horizon: int) -> GradeResult | None:
    profile = _forecast_node_profile(cur, run_id, delivery_date, horizon)
    if profile is None:
        return None
    settled = _settled_node_profile(cur, delivery_date)
    persistence = _settled_node_profile(cur, delivery_date - timedelta(days=1))
    model = _ordinal_profile(profile, len(profile)).abs()
    settled = _ordinal_profile(settled, len(profile)).abs()
    persistence = _ordinal_profile(persistence, len(profile)).abs()
    climatology = _trailing_settled_average(delivery_date, len(profile),
                                             _windowed_profiles(cur, delivery_date, 30, nodes=True))
    if climatology is not None:
        climatology = climatology.abs()
    return grade_profiles(model, settled, persistence,
                          settled_bound=settled.gt(NODE_CONGESTION_EPSILON),
                          climatology=climatology, top_fraction=0.10)


def serialize_grade_half(result: GradeResult) -> dict:
    """Return transport-neutral data for the Brief grade's one subject."""
    return {
        "graded": True,
        "universe_size": len(result.universe),
        "model": result.model.__dict__,
        "persistence": result.persistence.__dict__,
        "climatology": None if result.climatology is None else result.climatology.__dict__,
        "support": None if result.support is None else result.support.__dict__,
    }
