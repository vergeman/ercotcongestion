"""Backfill an existing bp_ercot.npz into Postgres.

Use this when you have a run whose npz is already on disk and want to
persist it without rerunning the fit — e.g. an older run predating the
runner's ``--persist`` flag, or a sweep run you've decided to promote after
the fact.

For fresh runs, prefer ``runner.py --persist [--promote]`` — it fits and
persists in one step, sharing the same helpers in ``persist.py``.

Usage (runs inside the ``compute`` docker service; needs psycopg + db)::

    docker compose run --rm compute \
      python -m compute.implied_binding_proximity.ingest \
        --run-id ibp_sweep_w60_r7_l0.1_s100_h25 \
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

from .persist import (
    DEFAULT_LAYER,
    check_ref_method,
    copy_bp_rows,
    delete_run,
    set_current_pointer,
)

log = logging.getLogger("compute.implied_binding_proximity.ingest")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"


def _load_npz(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    with np.load(path, allow_pickle=False) as d:
        hours = d["hours"]
        sps = d["settlement_points"]
        bp = d["bp_ercot"]
        params_raw = d["params"]
    params = json.loads(params_raw.item() if params_raw.ndim == 0 else str(params_raw))
    return hours, sps, bp, params


def ingest_run(
    run_id: str,
    *,
    runs_root: Path = RUNS_ROOT,
    promote: bool = False,
    layer: str = DEFAULT_LAYER,
) -> int:
    """Backfill ``run_id``'s ``bp_ercot.npz`` into Postgres; return rows written.

    The npz is authoritative: prior rows for ``run_id`` are cleared and
    replaced so the DB always matches the on-disk artifact. With
    ``promote=True`` the served pointer is flipped in the same transaction,
    so persist + promote are atomic.

    Shared by the ``ingest`` CLI and ``compute.promote`` so both write rows
    the same way. Raises ``FileNotFoundError`` if the npz is absent and
    ``ValueError`` if it was fit against a non-distributed-slack ref.
    """
    npz_path = runs_root / run_id / "ibp" / "bp_ercot.npz"
    if not npz_path.exists():
        raise FileNotFoundError(npz_path)

    hours, sps, bp, params = _load_npz(npz_path)
    check_ref_method(params.get("ref_method"))
    log.info(
        "loaded %s: hours=%d SPs=%d params=%s",
        npz_path, hours.shape[0], sps.shape[0], params,
    )

    with psycopg.connect(PG_DSN) as conn:
        n_deleted = delete_run(conn, run_id)
        log.info("cleared %d prior rows for run_id=%s", n_deleted, run_id)

        n_rows = copy_bp_rows(conn, run_id, hours, sps, bp)
        log.info("copied %d rows into implied_binding_proximity", n_rows)

        if promote:
            set_current_pointer(conn, layer, run_id)
            log.info("promoted layer=%s -> run_id=%s", layer, run_id)

        conn.commit()

    return n_rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", required=True)
    p.add_argument("--promote", action="store_true",
                   help="Point implied_binding_proximity_current[--layer] at "
                        "this run_id so the API starts serving it. Backfill "
                        "always writes rows to the DB; --promote decides "
                        "whether to also flip the served pointer.")
    p.add_argument("--layer", default=DEFAULT_LAYER,
                   help=f"Map layer --promote flips (default {DEFAULT_LAYER}).")
    p.add_argument("--runs-root", type=Path, default=RUNS_ROOT,
                   help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        ingest_run(
            args.run_id,
            runs_root=args.runs_root,
            promote=args.promote,
            layer=args.layer,
        )
    except FileNotFoundError as e:
        log.error("bp_ercot.npz not found at %s", e)
        return 2
    except ValueError as e:
        log.error("%s", e)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
