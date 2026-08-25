"""Shared Postgres persistence for forecast panels and publication state.

This module owns the forecast-nodal panel, SF+μ artifact, and current-pointer
writes. Callers retain transaction ownership: they decide when to commit or roll
back after writing rows, artifacts, and finally the pointer.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

from compute.time import ct_day_bounds, delivery_date_of
from compute.projection.codecs import build_sf_mu_artifact, load_nodal

log = logging.getLogger(__name__)

FORECAST_LAYER = "ercot"


def _delivery_dates(ts: pd.Series) -> pd.Series:
    """Return the CT calendar date for each tz-aware UTC interval."""
    return delivery_date_of(ts)


def nodal_to_db(npz_path: str, conn, *, run_id: str,
                delivery_date=None, horizon: int = 1) -> int:
    """Load a nodal panel and ``COPY`` it into ``forecast_nodal`` for ``run_id``.

    Re-runs delete and replace either the requested CT-day timestamp window or the
    full run, always scoped to ``horizon``. The caller owns the transaction and
    promotes the pointer only after this write succeeds.
    """
    target = pd.Timestamp(delivery_date).date() if delivery_date is not None else None
    df = load_nodal(npz_path)
    df = df.assign(delivery_date=_delivery_dates(df["ts"]))
    if target is not None:
        df = df[df["delivery_date"] == target]

    with conn.cursor() as cur:
        if target is not None:
            ts_lo, ts_hi = ct_day_bounds(target)
            cur.execute(
                "DELETE FROM forecast_nodal WHERE run_id = %s AND horizon = %s "
                "AND ts >= %s AND ts < %s", (run_id, horizon, ts_lo, ts_hi))
        else:
            cur.execute("DELETE FROM forecast_nodal WHERE run_id = %s "
                        "AND horizon = %s", (run_id, horizon))

    ts_iso = df["ts"].astype(str).to_numpy()
    dd_iso = df["delivery_date"].astype(str).to_numpy()
    sp = df["settlement_point"].to_numpy()
    p10, p50, p90 = (df[c].to_numpy(np.float64) for c in ("p10", "p50", "p90"))
    point = df["point"].to_numpy(np.float64)

    def _f(v) -> float | None:
        return v if np.isfinite(v) else None

    sql = ("COPY forecast_nodal (run_id, delivery_date, ts, settlement_point, "
           "p10, p50, p90, point, horizon) FROM STDIN")
    n = len(df)
    hint = " — this can take a minute" if n > 1_000_000 else ""
    log.info("writing %s rows to forecast_nodal for run_id=%s (horizon %d)%s",
             f"{n:,}", run_id, horizon, hint)
    with conn.cursor() as cur, cur.copy(sql) as cp:
        for i in range(n):
            cp.write_row((run_id, dd_iso[i], ts_iso[i], sp[i],
                          _f(p10[i]), _f(p50[i]), _f(p90[i]), _f(point[i]), horizon))
    return n


def upsert_pointer(conn, layer: str, run_id: str) -> None:
    """Set ``forecast_current[layer]`` to ``run_id`` after all rows land."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_current (layer, run_id) VALUES (%s, %s) "
            "ON CONFLICT (layer) DO UPDATE "
            "SET run_id = EXCLUDED.run_id, promoted_at = now()",
            (layer, run_id))


def sf_artifact_to_db(conn, *, run_id: str, delivery_date, sf_npz: bytes,
                      horizon: int = 1) -> None:
    """Upsert one SF+μ artifact; the caller owns the transaction."""
    dd = pd.Timestamp(delivery_date).date()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_sf_artifact (run_id, delivery_date, sf_npz, horizon) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (run_id, delivery_date, horizon) DO UPDATE "
            "SET sf_npz = EXCLUDED.sf_npz",
            (run_id, dd, sf_npz, horizon))


def persist_sf_mu_artifact(conn, SF: pd.DataFrame, E_mu: pd.DataFrame, *,
                           run_id: str, delivery_date, npz_dir: str | None = None,
                           horizon: int = 1) -> bytes:
    """Build and persist one SF+μ artifact, optionally saving its identical npz."""
    blob = build_sf_mu_artifact(SF, E_mu)
    if npz_dir is not None:
        dd = pd.Timestamp(delivery_date).date()
        with open(os.path.join(npz_dir, f"sf_mu_{run_id}_{dd.isoformat()}h{horizon}.npz"),
                  "wb") as fh:
            fh.write(blob)
    sf_artifact_to_db(conn, run_id=run_id, delivery_date=delivery_date, sf_npz=blob,
                      horizon=horizon)
    return blob
