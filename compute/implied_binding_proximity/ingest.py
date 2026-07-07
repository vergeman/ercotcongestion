"""Ingest a promoted bp_ercot run into Postgres.

Loads ``runs/<run_id>/ibp/bp_ercot.npz`` and writes the unpivoted
(ts, settlement_point, bp) grid into ``implied_binding_proximity`` under the
given ``run_id``. Optionally flips the ``implied_binding_proximity_current``
pointer so the API starts serving this run.

Only the ``system_lambda`` reference method is supported — that's the
distributed-slack ref used to fit the SFs. Other refs would produce a
``bp_ercot`` that isn't comparable to what the API expects.

Usage (runs inside the ``compute`` docker service; needs psycopg + db)::

    docker compose run --rm compute \\
      python -m compute.implied_binding_proximity.ingest \\
        --run-id ibp_sweep_w60_r7_l0.01 \\
        [--layer ercot] [--promote]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import psycopg

from compute.config import PG_DSN

log = logging.getLogger("compute.implied_binding_proximity.ingest")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

REQUIRED_REF_METHOD = "system_lambda"
DEFAULT_LAYER = "ercot"


def _load_npz(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    with np.load(path, allow_pickle=False) as d:
        hours = d["hours"]
        sps = d["settlement_points"]
        bp = d["bp_ercot"]
        params_raw = d["params"]
    params = json.loads(params_raw.item() if params_raw.ndim == 0 else str(params_raw))
    return hours, sps, bp, params


def _copy_rows(conn, run_id: str, hours: np.ndarray, sps: np.ndarray, bp: np.ndarray) -> int:
    """Unpivot bp[hour, sp] to long rows and stream via COPY.

    Skip NaN entries — bp_ercot has holes where a refit window didn't cover a
    settlement point. Copying NaN would violate ``bp REAL NOT NULL``.
    """
    n_rows = 0
    hours_iso = [str(h) for h in hours]
    sps_str = [str(s) for s in sps]
    sql = (
        "COPY implied_binding_proximity "
        "(ts, settlement_point, bp, run_id) FROM STDIN"
    )
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", required=True)
    p.add_argument("--layer", default=DEFAULT_LAYER,
                   help=f"Map layer this run serves (default {DEFAULT_LAYER}).")
    p.add_argument("--promote", action="store_true",
                   help="After a successful ingest, point "
                        "implied_binding_proximity_current[layer] at this run_id.")
    p.add_argument("--runs-root", type=Path, default=RUNS_ROOT,
                   help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    npz_path = args.runs_root / args.run_id / "ibp" / "bp_ercot.npz"
    if not npz_path.exists():
        log.error("bp_ercot.npz not found at %s", npz_path)
        return 2

    hours, sps, bp, params = _load_npz(npz_path)
    ref_method = params.get("ref_method")
    if ref_method != REQUIRED_REF_METHOD:
        log.error(
            "refusing to ingest run with ref_method=%r (required %r). "
            "Only distributed-slack fits are DB-compatible.",
            ref_method, REQUIRED_REF_METHOD,
        )
        return 2

    log.info(
        "loaded %s: hours=%d SPs=%d params=%s",
        npz_path, hours.shape[0], sps.shape[0], params,
    )

    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM implied_binding_proximity WHERE run_id = %s",
                (args.run_id,),
            )
            log.info("cleared %d prior rows for run_id=%s", cur.rowcount, args.run_id)

        n_rows = _copy_rows(conn, args.run_id, hours, sps, bp)
        log.info("copied %d rows into implied_binding_proximity", n_rows)

        if args.promote:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO implied_binding_proximity_current "
                    "(layer, run_id) VALUES (%s, %s) "
                    "ON CONFLICT (layer) DO UPDATE "
                    "SET run_id = EXCLUDED.run_id, promoted_at = now()",
                    (args.layer, args.run_id),
                )
            log.info("promoted layer=%s -> run_id=%s", args.layer, args.run_id)

        conn.commit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
