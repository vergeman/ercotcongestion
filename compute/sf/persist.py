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

import json
import logging
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
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


def delete_sf_run(conn, run_id: str) -> tuple[int, int]:
    """Clear any prior SF rows for ``run_id`` from both S0b tables.

    Mirrors ``delete_run`` for the bp path — makes ``--persist-sf`` idempotent.
    Returns ``(n_sf_rows, n_meta_rows)`` deleted.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM implied_shift_factors WHERE run_id = %s", (run_id,)
        )
        n_sf = cur.rowcount
        cur.execute(
            "DELETE FROM sf_window_meta WHERE run_id = %s", (run_id,)
        )
        n_meta = cur.rowcount
    return n_sf, n_meta


def copy_sf_rows(
    conn,
    run_id: str,
    window_start,
    SF: pd.DataFrame,
    threshold: float,
) -> int:
    """Stream one refit window's SF matrix via ``COPY FROM STDIN``.

    ``SF`` is (constraint_key × settlement_point); it is unpivoted to
    ``(run_id, window_start, constraint_key, settlement_point, sf)``. Entries
    with ``|sf| < threshold`` or non-finite are skipped — the matrix is dense
    but mostly negligible, and ``sf REAL NOT NULL`` would reject NaN. Returns
    the number of rows written.
    """
    if SF.empty:
        return 0
    ws = str(window_start)
    keys = [str(k) for k in SF.index]
    sps = [str(s) for s in SF.columns]
    values = SF.to_numpy(dtype=float)
    sql = (
        "COPY implied_shift_factors "
        "(run_id, window_start, constraint_key, settlement_point, sf) "
        "FROM STDIN"
    )
    n_rows = 0
    with conn.cursor() as cur, cur.copy(sql) as cp:
        for i, key in enumerate(keys):
            row = values[i]
            for j, sp in enumerate(sps):
                v = float(row[j])
                if not np.isfinite(v) or abs(v) < threshold:
                    continue
                cp.write_row((run_id, ws, key, sp, v))
                n_rows += 1
    return n_rows


def delete_constraint_geo(conn, run_id: str) -> int:
    """Clear any prior constraint_geo rows for ``run_id``. Makes the geo-persist
    idempotent (delete-then-copy), mirroring ``delete_sf_run`` for the SF path."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM constraint_geo WHERE run_id = %s", (run_id,))
        return cur.rowcount


def copy_constraint_geo_rows(conn, run_id: str, window_start, geo: pd.DataFrame) -> int:
    """Stream one refit window's constraint geography via ``COPY FROM STDIN``.

    ``geo`` is indexed by ``constraint_key`` with columns ``lat, lon, spread_km,
    kv_mean, kv_max, zone_shares (dict), max_abs_sf, binding_hours``. Non-finite
    floats become NULL — a constraint whose |SF| mass lands entirely on
    uncoordinated settlement points is an honest hole, not a fallback.
    ``zone_shares`` is serialized to JSON text for the ``jsonb`` column. Returns
    the number of rows written.
    """
    if geo.empty:
        return 0
    ws = str(window_start)
    sql = (
        "COPY constraint_geo "
        "(run_id, window_start, constraint_key, lat, lon, spread_km, "
        " kv_mean, kv_max, zone_shares, max_abs_sf, binding_hours) FROM STDIN"
    )

    def _f(v) -> float | None:
        v = float(v)
        return v if np.isfinite(v) else None

    n_rows = 0
    with conn.cursor() as cur, cur.copy(sql) as cp:
        for key, r in geo.iterrows():
            shares = r["zone_shares"]
            js = json.dumps(shares) if isinstance(shares, dict) and shares else None
            bh = r["binding_hours"]
            bh = int(bh) if bh is not None and np.isfinite(bh) else None
            cp.write_row((
                run_id, ws, str(key),
                _f(r["lat"]), _f(r["lon"]), _f(r["spread_km"]),
                _f(r["kv_mean"]), _f(r["kv_max"]),
                js, _f(r["max_abs_sf"]), bh,
            ))
            n_rows += 1
    return n_rows


def write_window_meta(conn, run_id: str, meta: Mapping) -> None:
    """Upsert one ``sf_window_meta`` row for a refit window.

    ``meta`` supplies the window/score spans and support counts. ``oos_r2`` and
    ``coverage`` default to NULL — S1 backfills them once OOS eval lands.
    Idempotent under the ``(run_id, window_start)`` PK so re-persist replaces.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sf_window_meta "
            "(run_id, window_start, window_end, score_start, score_end, "
            " n_kept, n_dropped, n_sf_clipped, fit_r2, oos_r2, coverage) "
            "VALUES (%(run_id)s, %(window_start)s, %(window_end)s, "
            " %(score_start)s, %(score_end)s, %(n_kept)s, %(n_dropped)s, "
            " %(n_sf_clipped)s, %(fit_r2)s, %(oos_r2)s, %(coverage)s) "
            "ON CONFLICT (run_id, window_start) DO UPDATE SET "
            " window_end = EXCLUDED.window_end, "
            " score_start = EXCLUDED.score_start, "
            " score_end = EXCLUDED.score_end, "
            " n_kept = EXCLUDED.n_kept, "
            " n_dropped = EXCLUDED.n_dropped, "
            " n_sf_clipped = EXCLUDED.n_sf_clipped, "
            " fit_r2 = EXCLUDED.fit_r2, "
            " oos_r2 = EXCLUDED.oos_r2, "
            " coverage = EXCLUDED.coverage",
            {
                "run_id": run_id,
                "oos_r2": None,
                "coverage": None,
                **meta,
            },
        )


def update_eval_metrics(conn, run_id: str, rows: Iterable,
                        tol_days: float = 3.5) -> int:
    """Backfill ``oos_r2`` / ``coverage`` / ``sf_stability`` on existing
    ``sf_window_meta`` rows.

    Matched by ``score_start`` to the **nearest** meta refit within ``tol_days``.
    The honest OOS fit and the persisted lookahead fit describe the same scored
    week, so ``score_start`` is the join key — but the two tools anchor their
    weekly refit grids on different first-days (``runner`` reads from
    ``start − window``; ``eval`` from ``start − 2×window``, clamped by data), so
    the grids land on a fixed sub-``refit_days`` phase offset and an equality
    join misses every row. A nearest match within ``refit_days/2`` (the
    ``sf_decay`` idiom) recovers the bijection: each meta refit takes the single
    closest eval week or stays NULL, and the ≤``tol_days`` shift is immaterial to
    these caveated confidence labels (``sf_stability`` moves slowly across
    refits).

    ``rows``: iterable of ``(score_start, oos_r2, coverage, sf_stability)``,
    ``score_start`` a tz-aware datetime, metrics possibly ``None``
    (``sf_stability`` is NULL for the earliest weeks, which lack the 2×window of
    history the disjoint correlation needs). Meta refits with no eval week within
    ``tol_days`` (the current window, whose score period isn't realized yet) stay
    NULL. Returns the number of meta rows updated.
    """
    eval_rows = [r for r in rows]
    if not eval_rows:
        return 0
    eval_idx = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in eval_rows])
    order = eval_idx.argsort()               # nearest-search needs monotonic
    eval_idx = eval_idx[order]
    eval_vals = [eval_rows[i] for i in order]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT score_start FROM sf_window_meta WHERE run_id = %s "
            "ORDER BY score_start",
            (run_id,),
        )
        meta_starts = [r[0] for r in cur.fetchall()]
    if not meta_starts:
        return 0

    tol = pd.Timedelta(days=tol_days)
    n = 0
    with conn.cursor() as cur:
        for target in meta_starts:
            ts = pd.Timestamp(target)
            j = eval_idx.get_indexer([ts], method="nearest")[0]
            if j < 0 or abs(eval_idx[j] - ts) > tol:
                continue
            _, oos_r2, coverage, sf_stability = eval_vals[j]
            cur.execute(
                "UPDATE sf_window_meta "
                "SET oos_r2 = %s, coverage = %s, sf_stability = %s "
                "WHERE run_id = %s AND score_start = %s",
                (oos_r2, coverage, sf_stability, run_id, target),
            )
            n += cur.rowcount
    return n


def count_null_eval(conn, run_id: str) -> int:
    """How many ``sf_window_meta`` rows for ``run_id`` still lack ``oos_r2``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM sf_window_meta "
            "WHERE run_id = %s AND oos_r2 IS NULL",
            (run_id,),
        )
        return int(cur.fetchone()[0])


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
