"""Assemble hero slots from the served artifact and compact window reads."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import pandas as pd

from compute.analysis.hero import classify_slots
from compute.analysis.hero_window import (
    daily_total,
    load_constraint_days,
    load_constraint_geo,
    load_load_condition,
    summarize_load_condition,
)
from compute.analysis.metadata import load_sp_metadata
from compute.sf.project import load_sf_mu


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


def _zone_summary(weights: pd.Series, geo_rows: list[dict[str, Any]], artifact) -> dict[str, Any]:
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
    nodal = -(artifact.SF.T @ weights.reindex(artifact.SF.index).fillna(0.0))
    node_zones: dict[str, float] = defaultdict(float)
    for sp, meta in load_sp_metadata(artifact.SF.columns).items():
        if meta.get("load_zone"):
            node_zones[str(meta["load_zone"]).lower().removeprefix("lz_")] += abs(float(nodal[sp]))
    node_total = sum(node_zones.values())
    return {
        "zone_shares": shares,
        "node_zone_shares": ({z: value / node_total for z, value in node_zones.items()}
                             if node_total else {}),
        "geo_as_of": next(iter(stamps)) if len(stamps) == 1 else None,
    }


def _magnitude_summary(rows: list[dict[str, Any]], delivery_date: date, *, days: int,
                       basis: str, n_keys: int) -> dict[str, Any]:
    values = daily_total(rows, delivery_date, days=days)
    return {"value": values[-1], "prior": values[:-1], "basis": basis, "n_keys": n_keys}


def build_hero(conn, run_id: str, delivery_date: date, horizon: int, basis: str,
               *, artifact=None, days: int = 30) -> dict[str, dict[str, Any]]:
    """Build classified hero slots for the requested forecast or settled basis.

    The same artifact vocabulary defines both bases, so a settled total is always
    compared with the matching cast-key historical series rather than every DAM
    constraint in the system.
    """
    if basis not in {"forecast", "settled"}:
        raise ValueError("basis must be 'forecast' or 'settled'")
    if artifact is None:
        with conn.cursor() as cur:
            artifact = _artifact(cur, run_id, delivery_date, horizon)
    if artifact is None:
        raise ValueError(f"artifact missing for {run_id=} {delivery_date=} {horizon=}")

    cast_keys = [str(key) for key in artifact.SF.index]
    cast_rows = load_constraint_days(conn, delivery_date, days=days, constraint_keys=cast_keys)
    all_rows = load_constraint_days(conn, delivery_date, days=days)
    weights = _weights(artifact, basis, cast_rows, delivery_date)
    if basis == "forecast":
        # Forecast μ exists for every artifact key, including keys with no prior DAM row.
        forecast_value = float(weights.sum())
        cast_summary = _magnitude_summary(cast_rows, delivery_date, days=days,
                                           basis="cast_keys", n_keys=len(cast_keys))
        cast_summary["value"] = forecast_value
    else:
        cast_summary = _magnitude_summary(cast_rows, delivery_date, days=days,
                                           basis="cast_keys", n_keys=len(cast_keys))
    all_summary = _magnitude_summary(all_rows, delivery_date, days=days,
                                     basis="all_keys",
                                     n_keys=len({row["constraint_key"] for row in all_rows
                                                 if row["delivery_date"] == delivery_date}))
    cast_summary["all_keys"] = all_summary

    condition = summarize_load_condition(load_load_condition(conn, delivery_date))
    if condition is None:
        condition = {"series": "load.system", "today": None, "median": None,
                     "pct": 0.0, "n": 0, "basis": "forecast"}
    geo = _zone_summary(weights, load_constraint_geo(conn), artifact)
    # Node-tier exceptions require untruncated node serving (0003).  Keep the
    # slot explicitly empty instead of implying a claim from the cast alone.
    exceptions = {"tier_0": 0, "tier_1": 0, "materiality": None}
    return classify_slots({"magnitude": cast_summary, "regime": condition,
                           "where": geo, "exceptions": exceptions})
