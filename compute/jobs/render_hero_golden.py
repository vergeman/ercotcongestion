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
    """Return the latest artifact track for each delivery day, oldest first."""
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
    """Render one stable audit row."""
    segments = render(slots)
    buckets = " ".join(f"{name}={slots[name]['bucket']}" for name in SLOT_NAMES)
    diagnostics = _diagnostics(slots)
    headline = "".join(part["text"] for part in segments["headline"])
    lede = "".join(part["text"] for part in segments["lede"])
    return f"{buckets}\t{diagnostics}\t{headline}\t{lede}"


def _diagnostics(slots: dict) -> str:
    """Render compact values that support the hero copy."""
    magnitude = slots["magnitude"]
    regime = slots["regime"]
    where = slots["where"]
    exceptions = slots["exceptions"]
    parts = [
        f"mag_rank={magnitude.get('rank', '-')}/{magnitude.get('n', '-')}",
        f"mag_ratio={float(magnitude['ratio']):.2f}" if magnitude.get("ratio") is not None
        else "mag_ratio=-",
        f"regime_pct={float(regime['pct']):.1f}" if regime.get("pct") is not None else "regime_pct=-",
        f"where_share={float(where['share']):.3f}" if where.get("share") is not None else "where_share=-",
    ]
    high_congestion = magnitude.get("high_congestion_hours")
    if high_congestion is not None:
        parts.extend((f"high_congestion_rank={high_congestion.get('rank', '-')}/{high_congestion.get('n', '-')}",
                      f"high_congestion_ratio={float(high_congestion['ratio']):.2f}"
                      if high_congestion.get("ratio") is not None else "high_congestion_ratio=-"))
    if exceptions.get("available") is False:
        parts.append("exceptions=unavailable")
    else:
        parts.extend((f"tier_0={exceptions.get('tier_0_count', len(exceptions.get('tier_0', [])))}",
                      f"tier_1={exceptions.get('tier_1_count', len(exceptions.get('tier_1', [])))}",
                      f"exception_count={exceptions.get('count', '-') }"))
    return " ".join(parts)


def render_audit(conn, run_id: str, days: list[tuple[date, int]], *, basis: str = "settled",
                 strict: bool = True) -> list[str]:
    """Render one hero per day and reject one-sided bucket results."""
    # Cache repeated support data for this audit only.
    from compute.analysis import hero_builder
    load_geo = hero_builder.load_constraint_geo
    load_metadata = hero_builder.load_sp_metadata
    if conn is not None:
        geo = load_geo(conn)
        metadata_cache: dict[tuple[str, ...], dict] = {}

        def cached_geo(_conn):
            return geo

        def cached_metadata(points):
            key = tuple(map(str, points))
            if key not in metadata_cache:
                metadata_cache[key] = load_metadata(points)
            return metadata_cache[key]

        hero_builder.load_constraint_geo = cached_geo
        hero_builder.load_sp_metadata = cached_metadata
    lines = []
    counts = {name: Counter() for name in SLOT_NAMES}
    available = Counter()
    try:
        for delivery_date, horizon in days:
            slots = build_hero(conn, run_id, delivery_date, horizon, basis).slots
            for name in SLOT_NAMES:
                if slots[name].get("available") is not False:
                    counts[name][slots[name]["bucket"]] += 1
                    available[name] += 1
            lines.append(f"{delivery_date.isoformat()}\t{line_for(slots)}")
    finally:
        if conn is not None:
            hero_builder.load_constraint_geo = load_geo
            hero_builder.load_sp_metadata = load_metadata
    if strict:
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
    parser.add_argument("--allow-dominant", action="store_true",
                        help="explicitly write a review snapshot despite a strict bucket-dominance finding")
    args = parser.parse_args(argv)

    from shared.settings import settings
    with psycopg.connect(settings.pg_dsn) as conn:
        lines = render_audit(conn, args.run_id,
                             available_days(conn, args.run_id, args.end_date), basis=args.basis,
                             strict=not args.allow_dominant)
    header = "# audit_mode=allow_dominant (explicit vocabulary-review override)\n" if args.allow_dominant else ""
    args.output.write_text(header + "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
