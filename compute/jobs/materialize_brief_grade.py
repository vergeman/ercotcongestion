"""Materialize the Brief's v6 grade track after DAM settlement.

This intentionally persists the same calculation served by ``/analysis/grade``;
``scoreboard_daily`` uses a different, nodal scorecard currency and must not be
substituted for the Brief's Detection/Magnitude/Timing cards.

One-time backfill of every previously served node grade:

    python -m compute.jobs.materialize_brief_grade --backfill-existing

Resume a date range by moving ``--end-date`` backward. The operation is
idempotent and replaces both Brief subjects for each existing node-grade key.

One-time local backfill for one run (ending at the latest settled Brief day):

    python -m compute.jobs.materialize_brief_grade \
        --run-id mu-all-v1 --delivery-date 2026-08-12 --days 31

For resumable contiguous 30-day batches, move the next end date back exactly
30 days (the range is inclusive):

    # 2026-07-14 through 2026-08-12
    python -m compute.jobs.materialize_brief_grade \
        --run-id mu-all-v1 --delivery-date 2026-08-12 --days 30

    # 2026-06-14 through 2026-07-13
    python -m compute.jobs.materialize_brief_grade \
        --run-id mu-all-v1 --delivery-date 2026-07-13 --days 30

    # 2026-05-15 through 2026-06-13
    python -m compute.jobs.materialize_brief_grade \
        --run-id mu-all-v1 --delivery-date 2026-06-13 --days 30
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row

from compute.analysis.brief_grade import (
    grade_constraint_profiles,
    grade_node_profiles,
    serialize_grade_half,
)
from shared.settings import settings


def materialize_day(conn, run_id: str, delivery_date: date, horizon: int) -> bool:
    """Upsert both independent Brief grade halves for one settled delivery day."""
    with conn.cursor(row_factory=dict_row) as cur:
        constraints = grade_constraint_profiles(cur, run_id, delivery_date, horizon)
        nodes = grade_node_profiles(cur, run_id, delivery_date, horizon)
        if constraints is None or nodes is None:
            return False
        for subject, result in (("constraints", constraints), ("nodes", nodes)):
            cur.execute(
                "INSERT INTO analysis_grade_daily "
                "(run_id, delivery_date, horizon, subject, model, persistence, detail) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb) "
                "ON CONFLICT (run_id, delivery_date, horizon, subject) DO UPDATE SET "
                "model = EXCLUDED.model, persistence = EXCLUDED.persistence, detail = EXCLUDED.detail, "
                "computed_at = now()",
                (run_id, delivery_date, horizon, subject,
                 psycopg.types.json.Jsonb(result.model.__dict__),
                 psycopg.types.json.Jsonb(result.persistence.__dict__),
                 psycopg.types.json.Jsonb(serialize_grade_half(result))),
            )
    conn.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--delivery-date", type=date.fromisoformat)
    parser.add_argument("--horizon", type=int, default=1, choices=(1, 2))
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Materialize this many days ending at --delivery-date, inclusive.",
    )
    parser.add_argument(
        "--backfill-existing",
        action="store_true",
        help="Re-score every existing node-grade key.",
    )
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    args = parser.parse_args()
    if args.backfill_existing and (args.run_id or args.delivery_date):
        parser.error(
            "--backfill-existing does not accept --run-id or --delivery-date"
        )
    if not args.backfill_existing and (not args.run_id or not args.delivery_date):
        parser.error(
            "--run-id and --delivery-date are required without --backfill-existing"
        )
    with psycopg.connect(settings.pg_dsn) as conn:
        if args.backfill_existing:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT DISTINCT run_id, delivery_date, horizon FROM analysis_grade_daily "
                    "WHERE subject = 'nodes' AND (%s IS NULL OR delivery_date >= %s) "
                    "AND (%s IS NULL OR delivery_date <= %s) "
                    "ORDER BY delivery_date, run_id, horizon",
                    (args.start_date, args.start_date, args.end_date, args.end_date),
                )
                keys = cur.fetchall()
            for key in keys:
                status = "materialized" if materialize_day(
                    conn, key["run_id"], key["delivery_date"], key["horizon"]
                ) else "skipped"
                print(
                    f"{key['delivery_date'].isoformat()} {key['run_id']} "
                    f"h{key['horizon']} {status}",
                    flush=True,
                )
        else:
            for offset in range(args.days - 1, -1, -1):
                day = args.delivery_date - timedelta(days=offset)
                status = (
                    "materialized"
                    if materialize_day(conn, args.run_id, day, args.horizon)
                    else "skipped"
                )
                print(f"{day.isoformat()} {status}", flush=True)


if __name__ == "__main__":
    main()
