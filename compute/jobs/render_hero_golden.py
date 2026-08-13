"""Render a deterministic 365-delivery-day hero review file.

Run against the same database the API serves, then check in the generated text:

    python -m compute.jobs.render_hero_golden --run-id mu-all-v1 \
      --end-date 2026-07-28 --output analysis/tests/fixtures/hero_headlines_365.txt
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

import psycopg

from compute.analysis.hero_builder import build_hero
from compute.analysis.phrases import render


SLOT_NAMES = ("magnitude", "regime", "where", "exceptions")


def available_days(conn, run_id: str, end_date: date, *, count: int = 365) -> list[tuple[date, int]]:
    """Select the latest served artifact track per delivery day, oldest first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT delivery_date, min(horizon) AS horizon
            FROM forecast_sf_artifact
            WHERE run_id = %s AND delivery_date <= %s
            GROUP BY delivery_date
            ORDER BY delivery_date DESC
            LIMIT %s
            """, (run_id, end_date, count))
        rows = cur.fetchall()
    if len(rows) != count:
        raise ValueError(f"need {count} artifact days through {end_date}; found {len(rows)}")
    return [(row[0], int(row[1])) for row in reversed(rows)]


def line_for(slots: dict) -> str:
    """A stable, compact line for code review rather than browser snapshots."""
    segments = render(slots)
    buckets = " ".join(f"{name}={slots[name]['bucket']}" for name in SLOT_NAMES)
    headline = "".join(part["text"] for part in segments["headline"])
    lede = "".join(part["text"] for part in segments["lede"])
    return f"{buckets}\t{headline}\t{lede}"


def render_golden(conn, run_id: str, days: list[tuple[date, int]]) -> list[str]:
    """Build forecast-basis hero text; one stable line per delivery day."""
    lines = []
    bucket_counts = {name: Counter() for name in SLOT_NAMES}
    for delivery_date, horizon in days:
        slots = build_hero(conn, run_id, delivery_date, horizon, "forecast")
        for name in SLOT_NAMES:
            bucket_counts[name][slots[name]["bucket"]] += 1
        lines.append(f"{delivery_date.isoformat()}\t{line_for(slots)}")
    for name, counts in bucket_counts.items():
        most_common = max(counts.values(), default=0)
        if most_common > len(days) / 2:
            raise ValueError(f"{name} bucket dominates golden file: {counts.most_common(1)[0]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    from shared.settings import settings
    with psycopg.connect(settings.pg_dsn) as conn:
        days = available_days(conn, args.run_id, args.end_date)
        lines = render_golden(conn, args.run_id, days)
    args.output.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
