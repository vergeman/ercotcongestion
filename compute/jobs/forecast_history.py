"""Persist daily per-constraint forecast μ totals from SF artifacts.

``forecast_sf_artifact`` is the compact source of record.  This module decodes
one artifact at a time and stores the inexpensive daily projection that history
readers need, without changing the artifact or its forecast fit.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from compute.projection.propagate import load_sf_mu


def rollup_rows(artifact) -> list[tuple[str, float, int]]:
    """Return one untruncated ``Σμ`` + nonzero-hour count per artifact key."""
    values = artifact.E_mu
    totals = values.sum(axis=0)
    hours = values.ne(0.0).sum(axis=0)
    return [(str(key), float(totals[key]), int(hours[key])) for key in values.columns]


def load_artifact(conn, run_id: str, delivery_date: date, horizon: int):
    """Load an artifact exactly on the horizon-aware rollup key, or ``None``."""
    with conn.cursor() as cur:
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


def persist_rollup(conn, run_id: str, delivery_date: date, horizon: int,
                   artifact) -> int:
    """Upsert an artifact's full, untruncated daily constraint vocabulary."""
    rows = [(run_id, delivery_date, horizon, key, value, hours)
            for key, value, hours in rollup_rows(artifact)]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO forecast_constraint_daily "
            "(run_id, delivery_date, horizon, constraint_key, forecast_mu, binding_hours) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, delivery_date, horizon, constraint_key) DO UPDATE SET "
            "forecast_mu = EXCLUDED.forecast_mu, binding_hours = EXCLUDED.binding_hours",
            rows,
        )
    return len(rows)
