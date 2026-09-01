"""Assemble hero slots from the served artifact and compact window reads."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from compute.analysis.hero import classify_regime, classify_slots
from compute.analysis.hero_queries import (
    HIGH_CONGESTION_CT_HOURS,
    daily_total,
    load_constraint_days,
    load_constraint_geo,
    load_forecast_constraint_days,
    load_load_condition,
    summarize_load_condition,
)
from compute.analysis.metadata import load_sp_metadata
from compute.projection.codecs import load_sf_mu
from compute.time import ERCOT_TZ


BENCHMARK_SP_FAMILIES = (
    (
        "load zones",
        ("LZ_HOUSTON", "LZ_NORTH", "LZ_SOUTH", "LZ_WEST"),
    ),
    (
        "hubs",
        ("HB_HOUSTON", "HB_NORTH", "HB_SOUTH", "HB_WEST"),
    ),
)
BENCHMARK_LABELS = {
    "LZ_HOUSTON": "Houston LZ",
    "LZ_NORTH": "North LZ",
    "LZ_SOUTH": "South LZ",
    "LZ_WEST": "West LZ",
    "HB_HOUSTON": "Houston Hub",
    "HB_NORTH": "North Hub",
    "HB_SOUTH": "South Hub",
    "HB_WEST": "West Hub",
}
# A $1/MWh mean over the established 15–18 CT congestion slice keeps numerical
# residue and insignificant opposite signs from replacing the broader regional
# description.
BENCHMARK_SPLIT_MIN = 1.0


@dataclass(frozen=True)
class HeroInputs:
    """Database-backed inputs shared by forecast and settled hero bases."""

    artifact: Any
    artifact_keys: list[str]
    artifact_rows: list[dict[str, Any]]
    high_congestion_rows: list[dict[str, Any]]
    all_rows: list[dict[str, Any]]
    forecast_rows: list[dict[str, Any]] | None
    geo_rows: list[dict[str, Any]]
    metadata: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class HeroBuild:
    """Complete displayed slots and the optional forecast comparison slots."""

    slots: dict[str, dict[str, Any]]
    forecast_slots: dict[str, dict[str, Any]] | None


def _artifact(cur, run_id: str, delivery_date: date, horizon: int):
    cur.execute(
        "SELECT sf_npz FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
        (run_id, delivery_date, horizon),
    )
    row = cur.fetchone()
    if row is None:
        return None
    blob = row["sf_npz"] if isinstance(row, dict) else row[0]
    return load_sf_mu(bytes(blob))


def _weights(artifact, basis: str, settled_rows: list[dict[str, Any]], delivery_date: date) -> pd.Series:
    if basis == "forecast":
        return artifact.E_mu.sum(axis=0)
    values = {row["constraint_key"]: float(row["value"]) for row in settled_rows
              if row["delivery_date"] == delivery_date}
    return pd.Series(values, dtype=float).reindex(artifact.SF.index).fillna(0.0)


def _benchmark_split(artifact) -> dict[str, Any] | None:
    """Return a material 15–18 CT opposing-sign pair among direct LZ/HB SPPs."""
    hourly = -(artifact.E_mu.reindex(columns=artifact.SF.index, fill_value=0.0) @ artifact.SF)
    index = pd.DatetimeIndex(hourly.index)
    if index.tz is not None:
        peak = hourly.loc[index.tz_convert(ERCOT_TZ).hour.isin(HIGH_CONGESTION_CT_HOURS)]
        if not peak.empty:
            hourly = peak
    for family, candidates in BENCHMARK_SP_FAMILIES:
        available = [sp for sp in candidates if sp in hourly.columns]
        if len(available) < 2:
            continue
        daily_mean = hourly[available].mean(axis=0)
        positive = str(daily_mean.idxmax())
        negative = str(daily_mean.idxmin())
        if (float(daily_mean[positive]) >= BENCHMARK_SPLIT_MIN
                and float(daily_mean[negative]) <= -BENCHMARK_SPLIT_MIN):
            return {
                "family": family,
                "positive": positive,
                "negative": negative,
                "positive_label": BENCHMARK_LABELS[positive],
                "negative_label": BENCHMARK_LABELS[negative],
                "positive_value": float(daily_mean[positive]),
                "negative_value": float(daily_mean[negative]),
                "spread": float(daily_mean[positive]) - float(daily_mean[negative]),
            }
    return None


def _zone_summary(weights: pd.Series, geo_rows: list[dict[str, Any]], artifact,
                  metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Combine constraint μ mass and persisted |SF|-zone shares."""
    geo = {str(row["constraint_key"]): row for row in geo_rows}
    zones: dict[str, float] = defaultdict(float)
    stamps = set()
    for key, weight in weights.items():
        row = geo.get(str(key))
        if row is None:
            continue
        stamps.add(str(row["geo_as_of"]))
        for zone, share in (row["zone_shares"] or {}).items():
            zones[str(zone).lower().removeprefix("lz_")] += abs(float(weight)) * float(share)
    total = sum(zones.values())
    shares = {zone: value / total for zone, value in zones.items()} if total else {}

    # Node geography is supporting context, not a hand-authored place label.
    # ``nodal`` is the signed congestion (SPP − λ) contribution per settlement
    # point: > 0 is scarcity that lifts local price, < 0 is export/oversupply
    # that depresses it.  Shares keep the magnitude; ``node_zone_net`` keeps the
    # sign so the leading zone can be reported as above/below the system price.
    nodal = -(artifact.SF.T @ weights.reindex(artifact.SF.index).fillna(0.0))
    node_zones: dict[str, float] = defaultdict(float)
    node_net: dict[str, float] = defaultdict(float)
    node_count: dict[str, int] = defaultdict(int)
    for sp, meta in metadata.items():
        if meta.get("load_zone"):
            zone = str(meta["load_zone"]).lower().removeprefix("lz_")
            node_zones[zone] += abs(float(nodal[sp]))
            node_net[zone] += float(nodal[sp])
            node_count[zone] += 1
    node_total = sum(node_zones.values())
    return {
        "zone_shares": shares,
        "node_zone_shares": ({z: value / node_total for z, value in node_zones.items()}
                             if node_total else {}),
        "node_zone_net": {z: node_net[z] / node_count[z] for z in node_net},
        "benchmark_split": _benchmark_split(artifact),
        "geo_as_of": next(iter(stamps)) if len(stamps) == 1 else None,
    }


def _magnitude_summary(rows: list[dict[str, Any]], delivery_date: date, *, days: int,
                       basis: str, n_keys: int) -> dict[str, Any]:
    values = daily_total(rows, delivery_date, days=days)
    return {"value": values[-1], "prior": values[:-1], "basis": basis, "n_keys": n_keys}


def _forecast_high_congestion_value(artifact) -> float:
    """Sum forecast μ over the empirical high-congestion CT slice."""
    index = pd.DatetimeIndex(artifact.E_mu.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    mask = index.tz_convert(ERCOT_TZ).hour.isin(HIGH_CONGESTION_CT_HOURS)
    return float(artifact.E_mu.loc[mask].sum(axis=0).sum())


def _exception_summary(rows: list[dict[str, Any]], delivery_date: date,
                       artifact_keys: list[str], *, days: int) -> dict[str, Any]:
    """Find DAM-active constraints that the day's artifact does not model.

    A candidate's rank is over its own complete delivery-day series, with absent
    DAM rows treated as zero.  This is deliberately constraint-level: node
    materiality and coordinate de-duplication belong to the later Standouts
    work, not to the hero's coverage signal.
    """
    artifact_key_set = set(artifact_keys)
    values: dict[str, dict[date, float]] = defaultdict(dict)
    for row in rows:
        key = str(row["constraint_key"])
        if key not in artifact_key_set:
            values[key][row["delivery_date"]] = float(row["value"])

    prior_days = [delivery_date - timedelta(days=offset) for offset in range(days, 0, -1)]
    tier_0: list[dict[str, Any]] = []
    tier_1: list[dict[str, Any]] = []
    for key, daily in values.items():
        value = daily.get(delivery_date, 0.0)
        if value == 0:
            continue
        prior = [daily.get(day, 0.0) for day in prior_days]
        rank = 1 + sum(other >= value for other in prior)
        candidate = {"constraint_key": key, "value": value, "rank": rank, "n": days + 1}
        if not any(prior):
            tier_0.append(candidate)
        if rank <= 3:
            tier_1.append(candidate)
    order = lambda item: (-abs(float(item["value"])), item["constraint_key"])
    return {"available": True, "tier_0": sorted(tier_0, key=order),
            "tier_1": sorted(tier_1, key=order)}


def build_hero_condition(conn, delivery_date: date) -> dict[str, Any]:
    """Build the load-condition slot used by the hero's stat boxes."""
    condition = summarize_load_condition(load_load_condition(conn, delivery_date))
    if condition is None:
        condition = {"series": "load.system", "today": None, "median": None,
                     "pct": 0.0, "n": 0, "basis": "forecast"}
    return classify_regime(condition)


def _load_inputs(conn, run_id: str, delivery_date: date, horizon: int, *, artifact,
                 days: int, include_forecast_history: bool) -> HeroInputs:
    artifact_keys = [str(key) for key in artifact.SF.index]
    artifact_rows = load_constraint_days(
        conn, delivery_date, days=days, constraint_keys=artifact_keys)
    high_congestion_rows = load_constraint_days(
        conn, delivery_date, days=days, constraint_keys=artifact_keys,
        ct_hours=HIGH_CONGESTION_CT_HOURS)
    all_rows = load_constraint_days(conn, delivery_date, days=days)
    forecast_rows = (
        load_forecast_constraint_days(
            conn, run_id, delivery_date, horizon, days=days,
            constraint_keys=artifact_keys)
        if include_forecast_history else None
    )
    return HeroInputs(
        artifact=artifact,
        artifact_keys=artifact_keys,
        artifact_rows=artifact_rows,
        high_congestion_rows=high_congestion_rows,
        all_rows=all_rows,
        forecast_rows=forecast_rows,
        geo_rows=load_constraint_geo(conn),
        metadata=load_sp_metadata(artifact.SF.columns),
    )


def _classify(inputs: HeroInputs, delivery_date: date, basis: str, *, days: int,
              condition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifact = inputs.artifact
    weights = _weights(artifact, basis, inputs.artifact_rows, delivery_date)

    if basis == "forecast":
        if inputs.forecast_rows is None:
            raise ValueError("forecast history is required for the forecast hero basis")
        forecast_value = float(weights.sum())
        artifact_summary = _magnitude_summary(
            inputs.forecast_rows, delivery_date, days=days,
            basis="forecast_history_artifact_keys", n_keys=len(inputs.artifact_keys))
        artifact_summary["value"] = forecast_value
    else:
        artifact_summary = _magnitude_summary(
            inputs.artifact_rows, delivery_date, days=days,
            basis="artifact_keys", n_keys=len(inputs.artifact_keys))
    all_summary = _magnitude_summary(inputs.all_rows, delivery_date, days=days,
                                     basis="all_keys",
                                     n_keys=len({row["constraint_key"] for row in inputs.all_rows
                                                 if row["delivery_date"] == delivery_date}))
    artifact_summary["all_keys"] = all_summary
    high_congestion_summary = _magnitude_summary(
        inputs.high_congestion_rows, delivery_date, days=days,
        basis="artifact_keys", n_keys=len(inputs.artifact_keys))
    high_congestion_summary["hours_ct"] = list(HIGH_CONGESTION_CT_HOURS)
    if basis == "forecast":
        high_congestion_summary["value"] = _forecast_high_congestion_value(artifact)
    artifact_summary["high_congestion_hours"] = high_congestion_summary

    geo = _zone_summary(weights, inputs.geo_rows, artifact, inputs.metadata)
    exceptions = (_exception_summary(inputs.all_rows, delivery_date, inputs.artifact_keys, days=days)
                  if basis == "settled" else {"available": False})
    slots = classify_slots({"magnitude": artifact_summary, "regime": condition,
                           "where": geo, "exceptions": exceptions})
    return slots


def build_hero(conn, run_id: str, delivery_date: date, horizon: int, basis: str,
               *, artifact=None, days: int = 30,
               include_forecast_comparison: bool = False) -> HeroBuild:
    """Build one complete hero response from shared database inputs.

    forecast and settled versions of the hero use the same set of constraint
    keys - those present in that day’s forecast artifact.

    Settled totals are always compared with existing model-key history rather
    than every (and new) DAM constraint in the system.

    """
    if basis not in {"forecast", "settled"}:
        raise ValueError("basis must be 'forecast' or 'settled'")
    if artifact is None:
        with conn.cursor() as cur:
            artifact = _artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        raise ValueError(f"artifact missing for {run_id=} {delivery_date=} {horizon=}")

    inputs = _load_inputs(
        conn, run_id, delivery_date, horizon, artifact=artifact, days=days,
        include_forecast_history=basis == "forecast" or include_forecast_comparison)
    condition = build_hero_condition(conn, delivery_date)

    slots = _classify(inputs, delivery_date, basis, days=days, condition=condition)
    forecast_slots = (
        _classify(inputs, delivery_date, "forecast", days=days, condition=condition)
        if include_forecast_comparison else None
    )
    return HeroBuild(slots=slots, forecast_slots=forecast_slots)
