"""Persist the SF matrix and constraint geography into Postgres.

The map runner (``runner.py``) streams each refit window here: its
``implied_shift_factors`` matrix (``copy_sf_rows``) and one ``sf_window_meta``
row (``write_window_meta``). ``geo_persist.py`` writes the constraint-geo
overlay (``copy_constraint_geo_rows``); ``eval.py`` backfills the per-window OOS
metrics (``update_eval_metrics``). Every write is idempotent per ``run_id``
(delete-then-copy, or upsert), so a re-persist replaces cleanly.
"""
from __future__ import annotations

import json
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

REQUIRED_REF_METHOD = "system_lambda"


def check_ref_method(ref_method: str | None) -> None:
    """Guard against persisting a run fit against a non-distributed-slack ref.

    The SF matrix only makes sense to serve when the fit used ``system_lambda``
    (or another distributed-slack ref). Other refs would produce values that
    aren't comparable to what the map expects.
    """
    if ref_method != REQUIRED_REF_METHOD:
        raise ValueError(
            f"refusing to persist run with ref_method={ref_method!r} "
            f"(required {REQUIRED_REF_METHOD!r}). Only distributed-slack "
            f"fits are DB-compatible."
        )


def delete_sf_run(conn, run_id: str) -> tuple[int, int]:
    """Clear any prior SF rows for ``run_id`` from both S0b tables.

    Makes ``--persist-sf`` idempotent. Returns ``(n_sf_rows, n_meta_rows)``
    deleted.
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


def existing_sf_windows(conn, run_id: str) -> set:
    """Return the DISTINCT ``window_start`` values already in ``sf_window_meta``
    for ``run_id``.

    The incremental map runner converts these to ns-instants before scheduling
    chunks, so a weekly tick fits only new complete boundaries.

    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT window_start FROM sf_window_meta WHERE run_id = %s",
            (run_id,),
        )
        return {row[0] for row in cur.fetchall()}


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
    with ``|sf| < threshold`` or non-finite are skipped. Returns the number of
    rows written.

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

    ``geo`` is indexed by ``constraint_key`` with columns ``spread_km, kv_mean,
    kv_max, zone_shares (dict), max_abs_sf, n_rail, peak_offrail, binding_hours,
    ctype``. Non-finite floats become NULL — a constraint whose |SF| mass lands
    entirely on uncoordinated settlement points is an honest hole, not a fallback.
    ``zone_shares`` is serialized to JSON text for the ``jsonb`` column. Returns
    the number of rows written. (The centroid/medoid coordinate columns were
    dropped in 0112 — nothing served them; the zone/kV/spread metadata stays.)
    """
    if geo.empty:
        return 0
    ws = str(window_start)
    sql = (
        "COPY constraint_geo "
        "(run_id, window_start, constraint_key, spread_km, "
        " kv_mean, kv_max, zone_shares, max_abs_sf, n_rail, peak_offrail, "
        " binding_hours, ctype) FROM STDIN"
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
            nr = r["n_rail"]
            nr = int(nr) if nr is not None and np.isfinite(nr) else None
            ct = r.get("ctype")
            ct = str(ct) if ct is not None and not (isinstance(ct, float) and np.isnan(ct)) else None
            cp.write_row((
                run_id, ws, str(key),
                _f(r["spread_km"]),
                _f(r["kv_mean"]), _f(r["kv_max"]),
                js, _f(r["max_abs_sf"]), nr, _f(r["peak_offrail"]), bh,
                ct,
            ))
            n_rows += 1
    return n_rows


def write_window_meta(conn, run_id: str, meta: Mapping) -> None:
    """Upsert one ``sf_window_meta`` row for a refit window.

    ``meta`` supplies the window/score spans and support counts. ``sf_oos_r2`` and
    ``coverage`` default to NULL — S1 backfills them once OOS eval lands.
    Idempotent under the ``(run_id, window_start)`` PK so re-persist replaces.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sf_window_meta "
            "(run_id, window_start, window_end, score_start, score_end, "
            " n_kept, n_dropped, n_sf_clipped, sf_fit_r2, sf_oos_r2, coverage) "
            "VALUES (%(run_id)s, %(window_start)s, %(window_end)s, "
            " %(score_start)s, %(score_end)s, %(n_kept)s, %(n_dropped)s, "
            " %(n_sf_clipped)s, %(sf_fit_r2)s, %(sf_oos_r2)s, %(coverage)s) "
            "ON CONFLICT (run_id, window_start) DO UPDATE SET "
            " window_end = EXCLUDED.window_end, "
            " score_start = EXCLUDED.score_start, "
            " score_end = EXCLUDED.score_end, "
            " n_kept = EXCLUDED.n_kept, "
            " n_dropped = EXCLUDED.n_dropped, "
            " n_sf_clipped = EXCLUDED.n_sf_clipped, "
            " sf_fit_r2 = EXCLUDED.sf_fit_r2, "
            " sf_oos_r2 = EXCLUDED.sf_oos_r2, "
            " coverage = EXCLUDED.coverage",
            {
                "run_id": run_id,
                "sf_oos_r2": None,
                "coverage": None,
                **meta,
            },
        )


def update_eval_metrics(conn, run_id: str, rows: Iterable) -> int:
    """Backfill ``sf_oos_r2`` / ``coverage`` / ``sf_stability`` on existing
    ``sf_window_meta`` rows.

    Matched by ``(run_id, score_start)`` — the honest OOS fit uses a different
    ``window_start`` than the persisted lookahead fit, but both describe the
    same scored week, so ``score_start`` is the join key. Only rows already
    written by ``--persist-sf`` are touched; ``rows`` for weeks with no meta row
    match nothing. ``rows``: iterable of
    ``(score_start, sf_oos_r2, coverage, sf_stability)``, where ``score_start`` is a
    datetime and the metrics may be ``None`` (``sf_stability`` is NULL for the
    earliest scored weeks, which lack the 2×window of history the disjoint
    correlation needs). Returns the number of rows updated.
    """
    n = 0
    with conn.cursor() as cur:
        for score_start, sf_oos_r2, coverage, sf_stability in rows:
            cur.execute(
                "UPDATE sf_window_meta "
                "SET sf_oos_r2 = %s, coverage = %s, sf_stability = %s "
                "WHERE run_id = %s AND score_start = %s",
                (sf_oos_r2, coverage, sf_stability, run_id, score_start),
            )
            n += cur.rowcount
    return n


def count_null_eval(conn, run_id: str) -> int:
    """How many ``sf_window_meta`` rows for ``run_id`` still lack ``sf_oos_r2``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM sf_window_meta "
            "WHERE run_id = %s AND sf_oos_r2 IS NULL",
            (run_id,),
        )
        return int(cur.fetchone()[0])
