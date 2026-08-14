"""Materialize the Brief's v6 grade track after DAM settlement.

This intentionally persists the same calculation served by ``/analysis/grade``;
``scoreboard_daily`` uses a different, nodal scorecard currency and must not be
substituted for the Brief's Detection/Magnitude/Timing cards.

One-time local backfill (ending at the latest settled Brief day):

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

from api.analysis import _grade_constraint_profiles, _grade_half, _grade_node_profiles
from shared.settings import settings


def materialize_day(conn, run_id: str, delivery_date: date, horizon: int) -> bool:
    """Upsert both independent Brief grade halves for one settled delivery day."""
    with conn.cursor(row_factory=dict_row) as cur:
        constraints = _grade_constraint_profiles(cur, run_id, delivery_date, horizon)
        nodes = _grade_node_profiles(cur, run_id, delivery_date, horizon)
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
                 psycopg.types.json.Jsonb(_grade_half(result).model_dump(mode="json"))),
            )
    conn.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--delivery-date", required=True, type=date.fromisoformat)
    parser.add_argument("--horizon", type=int, default=1, choices=(1, 2))
    parser.add_argument("--days", type=int, default=1,
                        help="Materialize this many days ending at --delivery-date, inclusive.")
    args = parser.parse_args()
    with psycopg.connect(settings.pg_dsn) as conn:
        for offset in range(args.days - 1, -1, -1):
            day = args.delivery_date - timedelta(days=offset)
            status = "materialized" if materialize_day(conn, args.run_id, day, args.horizon) else "skipped"
            print(f"{day.isoformat()} {status}", flush=True)


if __name__ == "__main__":
    main()
