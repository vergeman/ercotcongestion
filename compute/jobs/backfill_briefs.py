"""Backfill the Analysis brief over a date range from already-written artifacts.

For each UTC delivery date in ``[--start, --end]`` that already has a
``forecast_sf_artifact``, this re-ranks that day's SF+μ̂ into the brief the
Analysis view serves (docs/daily_brief_engine.md) and upserts it into
``analysis_brief`` — the SAME ``compute_brief``/``persist_brief`` path the live
tick's ``_brief_latest`` uses, so a backfilled brief is identical to what the live
job would have emitted.

CHEAP, not a refit. Unlike ``backfill_artifacts`` (which refits per day at ~16 GiB),
this never fits anything: per day it reads one artifact blob + the day's DAM and
re-ranks (F1–F6). F6 after-action fills automatically for days whose DAM has landed;
future/unrealized days get the forward, forecast-basis brief only. It is the
companion to ``backfill_artifacts``: that writes the artifacts, this briefs them.

  Resumable — skips dates already in ``analysis_brief`` (``--no-skip-existing``
              forces a rewrite), so an interrupted run picks up where it stopped.
  Fail-soft — a date whose brief build raises is logged and skipped
              (``--stop-on-error`` aborts instead). A date with no artifact is not
              an error — there is nothing to brief; it is counted and skipped.

  python -m compute.jobs.backfill_briefs --run-id mu-all-v1 \\
      --start 2025-01-08 --end 2025-05-31 --to-db
"""
from __future__ import annotations

import argparse
import logging
import os
import time

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from compute.jobs.daily_brief import _served_horizon, compute_brief, persist_brief
from compute.jobs.daily_forecast import _as_utc_day

log = logging.getLogger("compute.jobs.backfill_briefs")


def _dsn() -> str:
    return (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
            f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")


def _distinct_dates(dsn: str, table: str, run_id: str, lo, hi,
                    horizon: int | None) -> set:
    """delivery_dates present in ``table`` for run_id in [lo, hi] (optionally a horizon).

    ``table`` is a trusted literal (this module's callers only), never user input.
    """
    sql = (f"SELECT DISTINCT delivery_date FROM {table} "
           "WHERE run_id = %s AND delivery_date BETWEEN %s AND %s")
    params: list[object] = [run_id, lo.date(), hi.date()]
    if horizon is not None:
        sql += " AND horizon = %s"
        params.append(horizon)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return {r[0] for r in cur.fetchall()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", required=True, help="first UTC delivery date (inclusive)")
    p.add_argument("--end", required=True, help="last UTC delivery date (inclusive)")
    p.add_argument("--run-id", required=True,
                   help="model version whose artifacts to brief (e.g. mu-all-v1)")
    p.add_argument("--horizon", type=int, choices=(1, 2), default=None,
                   help="brief this artifact track only; default coalesces per day "
                        "(final when present, else preview) — matching what the "
                        "Analysis endpoint serves")
    p.add_argument("--to-db", action="store_true",
                   help="upsert analysis_brief per day; without it every brief is "
                        "built but nothing is written (dry run).")
    p.add_argument("--no-skip-existing", action="store_true",
                   help="recompute+rewrite dates already present in analysis_brief "
                        "(default skips them → resumable).")
    p.add_argument("--stop-on-error", action="store_true",
                   help="abort on the first failing date (default logs + skips it).")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    lo, hi = _as_utc_day(args.start), _as_utc_day(args.end)
    if hi < lo:
        p.error(f"--end {hi.date()} precedes --start {lo.date()}")
    days = pd.date_range(lo, hi, freq="D")     # UTC midnights, inclusive both ends
    dsn = _dsn()

    # Only days with an artifact can be briefed; days already briefed are skipped
    # (unless forced). A day with an artifact but no brief is exactly the backlog.
    have_artifact = _distinct_dates(dsn, "forecast_sf_artifact", args.run_id,
                                    lo, hi, args.horizon)
    have_brief = (set() if args.no_skip_existing
                  else _distinct_dates(dsn, "analysis_brief", args.run_id,
                                       lo, hi, args.horizon))
    no_artifact = [D for D in days if D.date() not in have_artifact]
    todo = [D for D in days
            if D.date() in have_artifact and D.date() not in have_brief]

    if no_artifact:
        log.info("%d of %d date(s) have no artifact — nothing to brief (run "
                 "backfill_artifacts first)", len(no_artifact), len(days))
    if have_brief:
        log.info("%d date(s) already have a brief — skipping (use "
                 "--no-skip-existing to rewrite)", len(have_brief & {D.date() for D in days}))

    log.info("backfilling briefs for %d date(s) [%s → %s], run_id=%s%s%s",
             len(todo), lo.date(), hi.date(), args.run_id,
             f" horizon={args.horizon}" if args.horizon else " (coalesced horizon)",
             "" if args.to_db else " (DRY RUN — nothing written)")

    written = failed = 0
    fail_dates: list = []
    t0 = time.perf_counter()
    # One connection for the whole run: briefs are seconds of frequent DB traffic
    # (read artifact + DAM, write brief), so the connection stays warm — no risk of
    # the server-side idle drop that makes backfill_artifacts reconnect per day.
    with psycopg.connect(dsn) as conn:
        for D in todo:
            dd = D.date()
            try:
                with conn.cursor(row_factory=dict_row) as cur:
                    horizon = args.horizon or _served_horizon(cur, args.run_id, dd)
                brief = compute_brief(conn, args.run_id, dd, horizon)
                if args.to_db:
                    persist_brief(conn, args.run_id, dd, horizon, brief)
                    conn.commit()
                else:
                    conn.rollback()   # dry run: drop any read snapshot, write nothing
            except (RuntimeError, ValueError, KeyError) as e:
                conn.rollback()
                failed += 1
                fail_dates.append(dd)
                log.warning("  %s  SKIP — %s", dd, e)
                if args.stop_on_error:
                    raise
                continue
            written += 1
            el = time.perf_counter() - t0
            eta = (el / written) * (len(todo) - written) / 60
            log.info("  %s  horizon=%d  (%d/%d written, %d failed)  eta %.1fm",
                     dd, horizon, written, len(todo), failed, eta)

    log.info("done: %d written, %d skipped-existing, %d no-artifact, %d failed%s",
             written, len(have_brief & {D.date() for D in days}), len(no_artifact),
             failed,
             (" — " + ", ".join(str(d) for d in fail_dates)) if fail_dates else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
