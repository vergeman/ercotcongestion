"""Generate a flat (non-regime) baseline of ERCOT snapshots over a date range.

One `status='ok'` snapshot per calendar date (the first interval of the day),
written as a flat JSON list of ISO timestamps. Complements
`extract_dates.py`, which produces a regime-balanced dict.

Usage::

    docker compose run --rm compute python -m compute.sample_specs.extract_flat_dates \
        [--start 2024-07-04] [--end 2025-07-04] [--output PATH]

    docker compose run --rm compute python -m compute.sample_specs.extract_flat_dates \
        --start 2025-01-01 --end 2026-06-29 --output flat_dates_2025-01-01_2026-06-29.json

Defaults cover a trailing 365-day window ending today (UTC). When `--output`
is omitted, the filename is derived as `flat_dates_<start>_<end>.json`.

NB: output directory defaults to /compute/sample_specs if file is unspecified,
else it outputs to /compute.

"""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from compute.config import PG_DSN

BASE_DIR = Path(__file__).parent

QUERY = """
    SELECT interval_ts
    FROM snapshot_meta
    WHERE status='ok'
       AND interval_ts >= %s
       AND interval_ts <  %s
    ORDER BY interval_ts ASC;
"""


def generate_flat(start: date, end: date, output_file: Path) -> None:
    start_ts = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_ts = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)

    with psycopg.connect(PG_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(QUERY, (start_ts, end_ts))
            timestamps = [row["interval_ts"].isoformat() for row in cur.fetchall()]

    with open(output_file, "w") as f:
        json.dump(timestamps, f, indent=2)

    print(
        f"Wrote {len(timestamps)} snapshots ({start.isoformat()} to "
        f"{end.isoformat()}, exclusive) to {output_file.name}"
    )


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = datetime.now(timezone.utc).date()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument(
        "--start",
        type=_parse_date,
        default=today - timedelta(days=365),
        help="Start date (inclusive, UTC, YYYY-MM-DD). Default: 365 days ago.",
    )
    p.add_argument(
        "--end",
        type=_parse_date,
        default=today,
        help="End date (exclusive, UTC, YYYY-MM-DD). Default: today.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Default: flat_dates_<start>_<end>.json "
        "under this module's directory.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.end <= args.start:
        raise SystemExit(
            f"--end ({args.end}) must be after --start ({args.start})"
        )
    output_file = args.output or (
        BASE_DIR / f"flat_dates_{args.start.isoformat()}_{args.end.isoformat()}.json"
    )
    generate_flat(start=args.start, end=args.end, output_file=output_file)


if __name__ == "__main__":
    main()
