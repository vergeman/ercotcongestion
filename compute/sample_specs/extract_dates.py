"""
Generate a regime-balanced baseline of ERCOT snapshots.

Four regimes (summer_peak, high_wind_west, mild_shoulder, winter_peak), N per
regime → 4·N total snapshots. Used as the canonical dates file for pipeline
runs and regression testing.

Usage::

    docker compose run --rm compute python -m compute.sample_specs.extract_dates \
        [--per-regime 30] [--output PATH]

Default `--per-regime 30` writes `reference_dates_120.json`. When `--output`
is omitted, the filename is derived as `reference_dates_<4*per_regime>.json`.
"""

import argparse
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from compute.config import PG_DSN

BASE_DIR = Path(__file__).parent

QUERIES = {
    "summer_peak": """
        WITH Ranked AS (
            SELECT interval_ts, n_binding_lines, total_load_mw,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY n_binding_lines DESC, total_load_mw DESC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND EXTRACT(MONTH FROM interval_ts) IN (6,7,8,9)
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY n_binding_lines DESC, total_load_mw DESC
        LIMIT %s;
    """,
    "high_wind_west": """
        WITH Ranked AS (
            SELECT interval_ts,
                   (wind_factor_by_region->>'west')::double precision as west_wind,
                   n_binding_lines,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY (wind_factor_by_region->>'west')::double precision DESC, n_binding_lines DESC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND (wind_factor_by_region->>'west')::double precision > 0.40
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY west_wind DESC, n_binding_lines DESC
        LIMIT %s;
    """,
    "mild_shoulder": """
        WITH Ranked AS (
            SELECT interval_ts, n_binding_lines, total_load_mw,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY n_binding_lines ASC, total_load_mw ASC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND EXTRACT(MONTH FROM interval_ts) IN (3,4,5,10,11)
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY n_binding_lines ASC, total_load_mw ASC
        LIMIT %s;
    """,
    "winter_peak": """
        WITH Ranked AS (
            SELECT interval_ts, total_load_mw, n_binding_lines,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY total_load_mw DESC, n_binding_lines DESC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND EXTRACT(MONTH FROM interval_ts) IN (12,1,2)
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY total_load_mw DESC, n_binding_lines DESC
        LIMIT %s;
    """,
}


def generate_baseline(per_regime: int, output_file: Path) -> None:
    baseline: dict[str, list[str]] = {}
    total_snapshots = 0

    with psycopg.connect(PG_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for regime, sql in QUERIES.items():
                cur.execute(sql, (per_regime,))
                timestamps = [row["interval_ts"].isoformat() for row in cur.fetchall()]
                baseline[regime] = timestamps
                total_snapshots += len(timestamps)
                print(f"Captured {len(timestamps)} snapshots for '{regime}'")

    with open(output_file, "w") as f:
        json.dump(baseline, f, indent=2)

    print(f"\nSuccessfully wrote {total_snapshots} total snapshots to {output_file.name}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument(
        "--per-regime",
        type=int,
        default=30,
        help="Snapshots to sample per regime (default: 30 → 120 total).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Default: reference_dates_<4*per_regime>.json "
        "under this module's directory.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.per_regime <= 0:
        raise SystemExit(f"--per-regime must be positive, got {args.per_regime}")
    output_file = args.output or BASE_DIR / f"reference_dates_{4 * args.per_regime}.json"
    generate_baseline(per_regime=args.per_regime, output_file=output_file)


if __name__ == "__main__":
    main()
