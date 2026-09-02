"""Database-backed inputs and neutral serialization for Brief grades.

This module deliberately depends only on the compute/runtime import boundary.
The API turns its neutral dictionaries into response models; scheduled jobs can
materialize exactly the same result without importing the API application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from psycopg.rows import tuple_row

from compute.analysis.grade import GradeResult, grade_profiles
from compute.projection.codecs import load_sf_mu
from compute.time import delivery_bounds

NODE_CONGESTION_EPSILON = 1e-6


@dataclass(frozen=True)
class SourceDefinition:
    """Brief-owned provenance for an independently graded profile."""

    id: str
    label: str
    definition: str
    result_field: str


SOURCE_DEFINITIONS = (
    SourceDefinition(
        "brief_model_artifact_profile",
        "Artifact profile forecast",
        "Forecast profile decoded from the served artifact.",
        "model",
    ),
    SourceDefinition(
        "brief_persistence_prior_settled_profile",
        "Prior-settled profile persistence",
        "Prior settled delivery-day profile.",
        "persistence",
    ),
    SourceDefinition(
        "brief_climatology_trailing_settled_profile",
        "Trailing-window Average (Baseline)",
        "Average of trailing settled subject profiles; not the projected Scoreboard baseline.",
        "climatology",
    ),
)


def _load_daily_artifact(cur, run_id: str, delivery_date: date, horizon: int):
    cur.execute(
        "SELECT sf_npz FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
        (run_id, delivery_date, horizon),
    )
    row = cur.fetchone()
    return None if row is None else load_sf_mu(bytes(row["sf_npz"]))


#
# Analysis Panels
#


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
    return frame.pivot(
        index="interval_ts", columns="constraint_key", values="shadow_price"
    ).sort_index()


def forecast_mu_profile(
    cur, run_id: str, delivery_date: date, horizon: int
) -> pd.DataFrame | None:
    start, end = delivery_bounds(delivery_date)
    artifact = _load_daily_artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        return None
    profile = artifact.E_mu.copy()
    profile.index = pd.to_datetime(profile.index, utc=True)
    return profile.loc[(profile.index >= start) & (profile.index < end)]


def settled_node_profile(cur, delivery_date: date) -> pd.DataFrame:
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
    return frame.pivot(
        index="interval_ts", columns="settlement_point", values="congestion"
    ).sort_index()


def forecast_node_profile(
    cur, run_id: str, delivery_date: date, horizon: int
) -> pd.DataFrame | None:
    artifact = _load_daily_artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        return None
    start, end = delivery_bounds(delivery_date)
    mu = artifact.E_mu.reindex(columns=artifact.SF.index, fill_value=0.0).fillna(0.0)
    profile = mu.dot(-artifact.SF)
    profile.index = pd.to_datetime(profile.index, utc=True)
    return profile.loc[(profile.index >= start) & (profile.index < end)]


def ordinal_profile(profile: pd.DataFrame, count: int) -> pd.DataFrame:
    """Align one delivery-day profile by interval order, padding to ``count``.
    (For when timestamps don't align but exactly but you want to align rows)"""
    result = profile.copy()
    result.index = pd.RangeIndex(len(result))
    return result.reindex(pd.RangeIndex(count))


def windowed_profiles(
    cur, delivery_date: date, days: int, *, nodes: bool
) -> dict[date, pd.DataFrame]:
    """Load prior settled profiles (constraints or sp's), grouped by
    Central-Time delivery day."""
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
    frame["delivery_date"] = (
        frame["interval_ts"].dt.tz_convert("America/Chicago").dt.date
    )
    return {
        day: group.pivot(index="interval_ts", columns=key, values="value").sort_index()
        for day, group in frame.groupby("delivery_date")
    }


def trailing_settled_average(
    delivery_date: date, count: int, by_day: dict[date, pd.DataFrame]
) -> pd.DataFrame | None:
    profiles = []
    for offset in range(1, 31):
        profile = by_day.get(delivery_date - timedelta(days=offset))
        if profile is None or profile.empty:
            return None
        profiles.append(ordinal_profile(profile, count))
    universe = list(
        dict.fromkeys(str(key) for profile in profiles for key in profile.columns)
    )
    if not universe:
        return None
    return sum(
        (
            profile.reindex(
                index=pd.RangeIndex(count), columns=universe, fill_value=0.0
            ).fillna(0.0)
            for profile in profiles
        )
    ) / len(profiles)


def grade_vocabulary(cur, delivery_date: date) -> list[str]:
    """vocabulary: set of constraints eligible for grading (universe)"""
    start, end = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT DISTINCT btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key "
        "FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts < %s AND shadow_price IS NOT NULL "
        "ORDER BY constraint_key",
        (start - timedelta(days=30), end),
    )
    return [str(row["constraint_key"]) for row in cur.fetchall()]


#
# Grade Node and Constraint Profiles
#


def grade_constraint_profiles(
    cur, run_id: str, delivery_date: date, horizon: int
) -> GradeResult | None:
    profile = forecast_mu_profile(cur, run_id, delivery_date, horizon)
    if profile is None:
        return None
    settled = settled_mu_profile(cur, delivery_date)
    persistence = settled_mu_profile(cur, delivery_date - timedelta(days=1))
    model = ordinal_profile(profile, len(profile))
    settled = ordinal_profile(settled, len(profile))
    persistence = ordinal_profile(persistence, len(profile))
    climatology = trailing_settled_average(
        delivery_date,
        len(profile),
        windowed_profiles(cur, delivery_date, 30, nodes=False),
    )
    return grade_profiles(
        model,
        settled,
        persistence,
        settled_bound=settled.notna(),
        climatology=climatology,
        universe=grade_vocabulary(cur, delivery_date),
    )


def grade_node_profiles(
    cur, run_id: str, delivery_date: date, horizon: int
) -> GradeResult | None:
    profile = forecast_node_profile(cur, run_id, delivery_date, horizon)
    if profile is None:
        return None
    settled = settled_node_profile(cur, delivery_date)
    persistence = settled_node_profile(cur, delivery_date - timedelta(days=1))
    model = ordinal_profile(profile, len(profile)).abs()
    settled = ordinal_profile(settled, len(profile)).abs()
    persistence = ordinal_profile(persistence, len(profile)).abs()
    climatology = trailing_settled_average(
        delivery_date,
        len(profile),
        windowed_profiles(cur, delivery_date, 30, nodes=True),
    )
    if climatology is not None:
        climatology = climatology.abs()
    return grade_profiles(
        model,
        settled,
        persistence,
        settled_bound=settled.gt(NODE_CONGESTION_EPSILON),
        climatology=climatology,
        top_fraction=0.10,
    )


def serialize_grade_half(result: GradeResult) -> dict:
    """Return transport-neutral data for the Brief grade's one subject."""
    source_metrics = [
        {"id": source.id, "metrics": getattr(result, source.result_field).__dict__}
        for source in SOURCE_DEFINITIONS
        if getattr(result, source.result_field) is not None
    ]
    return {
        "graded": True,
        "universe_size": len(result.universe),
        "support": None if result.support is None else result.support.__dict__,
        "sources": [
            {"id": source.id, "label": source.label, "definition": source.definition}
            for source in SOURCE_DEFINITIONS
            if getattr(result, source.result_field) is not None
        ],
        "source_metrics": source_metrics,
    }
