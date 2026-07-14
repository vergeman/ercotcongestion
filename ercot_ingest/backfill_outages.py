"""Backfill NP1-346-ER unplanned resource outages over a posted-date range.

plan/0089 commit 2. Runs only after commit 1 cleared Gate C (BUILD — 100% of outage MW
locatable via the authoritative crosswalk).

NP1-346 is an ARCHIVE product — a zip wrapping an xlsx, one document per posting date —
so it fits neither `backfill.py`'s JSON `ENDPOINTS` table (delivery-date filters, paged
JSON) nor its `client.get`. This is its own driver, launchable as a Job exactly like
`backfill_dam_close.py`:

    python /ercot_ingest/backfill_outages.py --start 2024-12-11 --end 2026-07-01 --resume

Pipeline: `ErcotClient.archive_index` → one document per posting date (the newest that
day) → `download_archive` → `outage_parse.parse_report` (unzip + xlsx) →
`loaders.load_resource_outages`. posted_date IS the vintage; the snapshot describes
posted_date − 3, and that lag is applied downstream (compute, commit 3), not here.

Idempotent: `--resume` skips posted_dates already in `ingest_log`, and the table's
ON CONFLICT DO NOTHING absorbs re-runs.
"""
import argparse
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import psycopg

from backfill import is_completed, log_completion   # shared ingest_log semantics
from ErcotClient import PG_DSN, ErcotClient
from loaders import load_resource_outages
from outage_parse import parse_report

PRODUCT = "NP1-346-ER"
ENDPOINT = "resource_outages"

# Panel start — the 240-day training window for backtest week 1 needs the covariate this
# far back, so the backfill defaults here rather than to the first scored week.
PANEL_START = date(2024, 12, 11)


def _day_window(d: date) -> tuple[datetime, datetime]:
    """The [00:00, +1d) UTC window that keys this posted_date in ingest_log."""
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def snapshot_docs(idx, start: date, end: date):
    """One document per posting date — the LATEST posted that day — within [start, end].

    A date can carry a report and a later correction; the newest posting is the vintage
    that would have been admissible at the next DAM close, so it is the one to store."""
    idx = idx.copy()
    idx["d"] = idx["posted"].dt.date
    idx = idx[(idx["d"] >= start) & (idx["d"] <= end)]
    return idx.sort_values("posted").groupby("d", as_index=False).last()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=date.fromisoformat, default=PANEL_START,
                   help="Inclusive posted_date start (default: panel start 2024-12-11).")
    p.add_argument("--end", type=date.fromisoformat,
                   default=datetime.now(timezone.utc).date(),
                   help="Inclusive posted_date end (default: today).")
    p.add_argument("--resume", action="store_true",
                   help="Skip posted_dates already logged in ingest_log.")
    args = p.parse_args(argv)
    if args.start > args.end:
        sys.exit("--start must be on or before --end")

    client = ErcotClient()
    docs = snapshot_docs(client.archive_index(PRODUCT), args.start, args.end)
    print(f"NP1-346 backfill: {len(docs)} snapshots {args.start} → {args.end}")

    with psycopg.connect(PG_DSN) as conn:
        for row in docs.itertuples():
            d = row.d
            win_start, win_end = _day_window(d)
            if args.resume and is_completed(conn, ENDPOINT, win_start, win_end):
                print(f"  [{ENDPOINT}] {d} — skip (already done)")
                continue
            try:
                df = parse_report(client.download_archive(PRODUCT, row.docId))
                n = load_resource_outages(conn, df, d)
                log_completion(conn, ENDPOINT, win_start, win_end, len(df), n)
                conn.commit()
                print(f"  [{ENDPOINT}] {d} — {len(df)} fetched, {n} new")
            except Exception as e:                       # noqa: BLE001
                conn.rollback()
                print(f"  [{ENDPOINT}] {d} — FAILED: {e}")
                traceback.print_exc(limit=2)

    print("\nBackfill complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
