"""Render the manually reviewed 365-day hero audit file.

This is deliberately not a serving or persistence path. It reads the same
sources as the endpoint and writes a checked-in text artifact for vocabulary
review:

    python -m compute.jobs.render_hero_golden --run-id mu-all-v1 \
      --end-date 2026-07-28 --output analysis/tests/fixtures/hero_audit_365.txt
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
    """A stable, compact row for code review rather than a browser snapshot."""
    segments = render(slots)
    buckets = " ".join(f"{name}={slots[name]['bucket']}" for name in SLOT_NAMES)
    headline = "".join(part["text"] for part in segments["headline"])
    lede = "".join(part["text"] for part in segments["lede"])
    return f"{buckets}\t{headline}\t{lede}"


def render_audit(conn, run_id: str, days: list[tuple[date, int]], *, basis: str = "settled") -> list[str]:
    """Render one on-demand hero per day and guard against available-bucket drift."""
    lines = []
    counts = {name: Counter() for name in SLOT_NAMES}
    available = Counter()
    for delivery_date, horizon in days:
        slots = build_hero(conn, run_id, delivery_date, horizon, basis)
        for name in SLOT_NAMES:
            if slots[name].get("available") is not False:
                counts[name][slots[name]["bucket"]] += 1
                available[name] += 1
        lines.append(f"{delivery_date.isoformat()}\t{line_for(slots)}")
    for name, bucket_counts in counts.items():
        if available[name] and max(bucket_counts.values()) > available[name] / 2:
            raise ValueError(f"{name} bucket dominates audit: {bucket_counts.most_common(1)[0]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--basis", choices=("forecast", "settled"), default="settled")
    args = parser.parse_args(argv)

    from shared.settings import settings
    with psycopg.connect(settings.pg_dsn) as conn:
        lines = render_audit(conn, args.run_id,
                             available_days(conn, args.run_id, args.end_date), basis=args.basis)
    args.output.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
