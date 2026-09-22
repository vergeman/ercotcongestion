"""Regrade an inclusive range of served daily Scoreboard keys."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import pandas as pd

from compute.jobs.grade_forecast_day import grade_day, persist_grades
from compute.time import normalize_ct_day

log = logging.getLogger(__name__)


@dataclass
class BackfillSummary:
    replaced: list[str] = field(default_factory=list)
    newly_materialized: list[str] = field(default_factory=list)
    dry_run: list[str] = field(default_factory=list)
    missing_artifact: list[str] = field(default_factory=list)
    ungradeable: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    stopped: bool = False


def _days(start, end) -> list[pd.Timestamp]:
    first, last = normalize_ct_day(start), normalize_ct_day(end)
    if first > last:
        raise ValueError("--start must be on or before --end")
    return [normalize_ct_day(day) for day in pd.date_range(first.date(), last.date(), freq="D")]


def _existing_rows(conn, run_id: str, D: pd.Timestamp, horizon: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM scoreboard_daily WHERE run_id = %s "
            "AND delivery_date = %s AND horizon = %s",
            (run_id, D.date(), horizon),
        )
        return int(cur.fetchone()[0])


def _failure_kind(exc: Exception) -> str:
    message = str(exc).lower()
    if "served sf artifact" in message:
        return "missing_artifact"
    if ("no served forecast" in message or "realized" in message
            or "no nodes shared" in message):
        return "ungradeable"
    return "failed"


def backfill_range(connect, *, run_id: str, horizon: int, start, end,
                   to_db: bool = False, stop_on_error: bool = False) -> BackfillSummary:
    """Regrade each inclusive CT date in fresh per-key database scopes.

    ``connect`` returns a new psycopg connection. A successful write commits one
    key; an error rolls back that key and leaves later dates eligible to run.
    """
    summary = BackfillSummary()
    for D in _days(start, end):
        day = str(D.date())
        try:
            with connect() as conn:
                existing = _existing_rows(conn, run_id, D, horizon)
                rows = grade_day(conn, D, run_id=run_id, horizon=horizon)
                if len(rows) != 5:
                    raise RuntimeError(f"expected five source grades, got {len(rows)}")
                if not to_db:
                    summary.dry_run.append(day)
                    log.info("%s DRY RUN — %d candidate source rows", day, len(rows))
                    continue
                persist_grades(conn, run_id, D, rows, horizon)
                conn.commit()
                (summary.replaced if existing else summary.newly_materialized).append(day)
                log.info("%s %s — 5 source rows", day,
                         "REPLACED" if existing else "MATERIALIZED")
        except Exception as exc:
            kind = _failure_kind(exc)
            getattr(summary, kind).append(day)
            log.warning("%s %s — %s", day, kind.upper(), exc)
            if stop_on_error:
                summary.stopped = True
                break
    return summary


def _report(summary: BackfillSummary) -> None:
    for name in ("replaced", "newly_materialized", "dry_run", "missing_artifact",
                 "ungradeable", "failed"):
        dates = getattr(summary, name)
        log.info("%s=%d dates=%s", name, len(dates), ",".join(dates) or "-")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--horizon", required=True, type=int, choices=(1, 2))
    parser.add_argument("--start", required=True, help="first CT delivery date (inclusive)")
    parser.add_argument("--end", required=True, help="last CT delivery date (inclusive)")
    parser.add_argument("--to-db", action="store_true", help="replace daily rows; default is dry run")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args(argv)
    try:
        _days(args.start, args.end)
    except ValueError as exc:
        parser.error(str(exc))

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    summary = backfill_range(lambda: psycopg.connect(dsn), run_id=args.run_id,
                             horizon=args.horizon, start=args.start, end=args.end,
                             to_db=args.to_db, stop_on_error=args.stop_on_error)
    _report(summary)
    return int(bool(summary.missing_artifact or summary.ungradeable or summary.failed))


if __name__ == "__main__":
    raise SystemExit(main())
