"""Backfill queryable daily forecast μ history from existing SF artifacts.

This does not refit or alter ``forecast_sf_artifact``.  It decodes one existing
artifact per requested CT delivery day and upserts its complete E_mu vocabulary.
Missing artifacts are expected holes and are logged rather than treated as errors.

  python -m compute.jobs.backfill_forecast_history --run-id mu-all-v1 \\
      --start 2025-01-08 --end 2026-08-12 --to-db
"""
from __future__ import annotations

import argparse
import logging
import os

import pandas as pd
import psycopg

from compute.jobs.daily_forecast import _as_ct_day
from compute.jobs.forecast_history import load_artifact, persist_rollup, rollup_rows


log = logging.getLogger("compute.jobs.backfill_forecast_history")


def _dsn() -> str:
    return (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
            f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", required=True, help="first CT delivery date (inclusive)")
    p.add_argument("--end", required=True, help="last CT delivery date (inclusive)")
    p.add_argument("--run-id", required=True, help="artifact model version to roll up")
    p.add_argument("--horizon", type=int, choices=(1, 2), default=1,
                   help="artifact horizon to roll up (default: final horizon 1)")
    p.add_argument("--to-db", action="store_true",
                   help="upsert rows; omit for a decode-only dry run")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    lo, hi = _as_ct_day(args.start), _as_ct_day(args.end)
    if hi < lo:
        p.error(f"--end {hi.date()} precedes --start {lo.date()}")

    # Calendar dates, not the tz-aware CT-midnight instants: only `.date()` is
    # used below, but stepping `freq="D"` on the fixed-UTC-offset instants
    # themselves would drift across a DST transition (0133) — see the identical
    # note in backfill_artifacts.py.
    days = pd.date_range(lo.date(), hi.date(), freq="D")
    written = missing = 0
    with psycopg.connect(_dsn()) as conn:
        for D in days:
            dd = D.date()
            artifact = load_artifact(conn, args.run_id, dd, args.horizon)
            if artifact is None:
                missing += 1
                log.info("%s SKIP — no forecast_sf_artifact (run_id=%s horizon=%d)",
                         dd, args.run_id, args.horizon)
                continue
            n = (persist_rollup(conn, args.run_id, dd, args.horizon, artifact)
                 if args.to_db else len(rollup_rows(artifact)))
            if args.to_db:
                conn.commit()
            else:
                conn.rollback()
            written += 1
            log.info("%s %s %d constraint rows", dd,
                     "UPSERT" if args.to_db else "DRY RUN", n)

    log.info("done: %d artifact day(s) rolled up, %d missing%s", written, missing,
             "" if args.to_db else " (DRY RUN — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
