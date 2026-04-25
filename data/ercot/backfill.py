"""
Backfill NP6-86-CD and NP3-233-CD over a date range.

Usage:
    python backfill.py --start 2026-02-23 --end 2026-04-23
    python backfill.py --start 2026-02-23 --end 2026-04-23 --endpoint shadow
    python backfill.py --start 2026-02-23 --end 2026-04-23 --resume

Chunks by day. Idempotent: re-running skips completed (endpoint, day) pairs.
"""
import argparse
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import psycopg

from ErcotClient import ErcotClient, PG_DSN
from loaders import load_shadow_prices, load_outages


ENDPOINTS = {
    "shadow": {
        "path": "/np6-86-cd/shdw_prices_bnd_trns_const",
        "loader": load_shadow_prices,
        "from_param": "SCEDTimestampFrom",
        "to_param": "SCEDTimestampTo",
    },
    "outages": {
        "path": "/np3-233-cd/hourly_res_outage_cap",
        "loader": load_outages,
        "from_param": "postedDatetimeFrom",
        "to_param": "postedDatetimeTo",
    },
}


def is_completed(conn, endpoint: str, start: datetime, end: datetime) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ingest_log WHERE endpoint = %s AND window_start = %s AND window_end = %s",
            (endpoint, start, end),
        )
        return cur.fetchone() is not None


def log_completion(conn, endpoint: str, start: datetime, end: datetime,
                   rows_fetched: int, rows_inserted: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_log (endpoint, window_start, window_end, rows_fetched, rows_inserted)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (endpoint, window_start, window_end)
            DO UPDATE SET rows_fetched = EXCLUDED.rows_fetched,
                          rows_inserted = EXCLUDED.rows_inserted,
                          completed_at = now()
            """,
            (endpoint, start, end, rows_fetched, rows_inserted),
        )


def daily_windows(start_date: date, end_date: date):
    """Yield (start_dt, end_dt) UTC datetimes for each day [start_date, end_date]."""
    d = start_date
    while d <= end_date:
        start_dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(days=1)
        yield start_dt, end_dt
        d += timedelta(days=1)


def backfill_one_window(client: ErcotClient, conn, endpoint_key: str,
                        start: datetime, end: datetime, resume: bool) -> None:
    cfg = ENDPOINTS[endpoint_key]

    if resume and is_completed(conn, endpoint_key, start, end):
        print(f"  [{endpoint_key}] {start.date()} — skip (already done)")
        return

    iso_from = start.strftime("%Y-%m-%dT%H:%M:%S")
    iso_to = end.strftime("%Y-%m-%dT%H:%M:%S")

    df = client.get(cfg["path"], **{
        cfg["from_param"]: iso_from,
        cfg["to_param"]: iso_to,
    })

    rows_fetched = len(df)
    rows_inserted = cfg["loader"](conn, df)
    log_completion(conn, endpoint_key, start, end, rows_fetched, rows_inserted)
    conn.commit()

    print(f"  [{endpoint_key}] {start.date()} — {rows_fetched} fetched, {rows_inserted} new")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC), inclusive")
    parser.add_argument("--endpoint", choices=["shadow", "outages", "both"], default="both")
    parser.add_argument("--resume", action="store_true",
                        help="Skip windows already in ingest_log")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    if start_date > end_date:
        sys.exit("--start must be on or before --end")

    keys = ["shadow", "outages"] if args.endpoint == "both" else [args.endpoint]

    client = ErcotClient()

    with psycopg.connect(PG_DSN) as conn:
        total_days = (end_date - start_date).days + 1
        print(f"Backfilling {keys} for {total_days} days: {start_date} → {end_date}")

        for start, end in daily_windows(start_date, end_date):
            for key in keys:
                try:
                    backfill_one_window(client, conn, key, start, end, args.resume)
                except Exception as e:
                    print(f"  [{key}] {start.date()} — FAILED: {e}")
                    traceback.print_exc(limit=2)
                    conn.rollback()
                    # continue to next window — don't abort entire run

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
