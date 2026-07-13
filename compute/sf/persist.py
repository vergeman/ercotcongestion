"""Shared helpers to persist a bp_ercot panel into Postgres.

Two callers:

* ``runner.py`` — the normal path. After writing ``bp_ercot.npz`` it calls
  these helpers directly so a single invocation fits, writes the npz, and
  updates the DB in one step.
* ``ingest.py`` — the backfill path for an npz already on disk (an older
  run, a run copied off a sweep host, etc.).

Both paths converge on the same row-writing routine so the DB view is
consistent regardless of how the panel got there.

``promote_layer`` is the standalone pointer-flip entry point used by
``compute.promote`` to unify filesystem-served state and DB-served state
under one operator command.
"""
from __future__ import annotations

import logging
from typing import Iterable

import numpy as np
import psycopg

from compute.config import PG_DSN

log = logging.getLogger("compute.sf.persist")

REQUIRED_REF_METHOD = "system_lambda"
DEFAULT_LAYER = "ercot"


def check_ref_method(ref_method: str | None) -> None:
    """Guard against persisting a run fit against a non-distributed-slack ref.

    bp_ercot only makes sense to serve when the fit used ``system_lambda``
    (or another distributed-slack ref). Other refs would produce values
    that aren't comparable to what the API expects.
    """
    if ref_method != REQUIRED_REF_METHOD:
        raise ValueError(
            f"refusing to persist run with ref_method={ref_method!r} "
            f"(required {REQUIRED_REF_METHOD!r}). Only distributed-slack "
            f"fits are DB-compatible."
        )


def delete_run(conn, run_id: str) -> int:
    """Clear any prior rows for ``run_id``. Makes re-persistence idempotent."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM implied_binding_proximity WHERE run_id = %s",
            (run_id,),
        )
        return cur.rowcount


def copy_bp_rows(
    conn,
    run_id: str,
    hours: Iterable,
    settlement_points: Iterable,
    bp: np.ndarray,
) -> int:
    """Stream the unpivoted (ts, sp, bp, run_id) grid via ``COPY FROM STDIN``.

    Skips non-finite entries — bp_ercot can carry NaN where a refit window
    didn't cover a settlement point, and ``bp REAL NOT NULL`` would reject
    them.
    """
    hours_iso = [str(h) for h in hours]
    sps_str = [str(s) for s in settlement_points]
    sql = (
        "COPY implied_binding_proximity "
        "(ts, settlement_point, bp, run_id) FROM STDIN"
    )
    n_rows = 0
    with conn.cursor() as cur, cur.copy(sql) as cp:
        for i, ts in enumerate(hours_iso):
            row = bp[i]
            for j, sp in enumerate(sps_str):
                v = float(row[j])
                if not np.isfinite(v):
                    continue
                cp.write_row((ts, sp, v, run_id))
                n_rows += 1
    return n_rows


def run_has_rows(conn, run_id: str) -> bool:
    """True if ``implied_binding_proximity`` has any rows for ``run_id``.

    Read-your-writes safe: called within the same transaction as a preceding
    ``copy_bp_rows`` (runner/ingest), it sees the not-yet-committed rows; called
    on a fresh connection (``promote_layer``), it sees only committed rows.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM implied_binding_proximity WHERE run_id = %s LIMIT 1",
            (run_id,),
        )
        return cur.fetchone() is not None


def set_current_pointer(conn, layer: str, run_id: str) -> None:
    """Upsert ``implied_binding_proximity_current[layer] = run_id``."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO implied_binding_proximity_current "
            "(layer, run_id) VALUES (%s, %s) "
            "ON CONFLICT (layer) DO UPDATE "
            "SET run_id = EXCLUDED.run_id, promoted_at = now()",
            (layer, run_id),
        )


def get_current_pointer(conn, layer: str) -> tuple[str, object] | None:
    """Return ``(run_id, promoted_at)`` for ``layer``, or None if unset."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, promoted_at FROM implied_binding_proximity_current "
            "WHERE layer = %s",
            (layer,),
        )
        row = cur.fetchone()
        return (row[0], row[1]) if row else None


def promote_layer(run_id: str, layer: str = DEFAULT_LAYER) -> bool:
    """Flip the IBP served pointer for ``layer`` to ``run_id``.

    Idempotent: returns True when the pointer moved, False when it was
    already at ``run_id`` (no write, no ``promoted_at`` bump).

    Raises ``ValueError`` if ``run_id`` has no rows in
    ``implied_binding_proximity`` — flipping the pointer at a row-less run
    would make the API serve empty windows (503). Persist the panel first
    (``runner --persist`` or ``ingest``).
    """
    with psycopg.connect(PG_DSN) as conn:
        current = get_current_pointer(conn, layer)
        if current is not None and current[0] == run_id:
            return False
        if not run_has_rows(conn, run_id):
            raise ValueError(
                f"refusing to promote layer={layer!r} to run_id={run_id!r}: "
                f"no rows in implied_binding_proximity for that run_id. "
                f"Persist the panel first (runner --persist / ingest)."
            )
        set_current_pointer(conn, layer, run_id)
        conn.commit()
        return True
