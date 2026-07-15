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

Recurring ingest reuses this same driver, folded into the single existing 15-minute
`ercot-ingest` cron: `live_updater` calls `update_recent()` each cycle, which is
self-throttling (see below) so NP1-346 — a once-daily feed — is fetched about once a day,
not every 15 minutes. `--lookback-days N` remains for a manual catch-up run.
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

# live_updater refresh window (UTC). NP1-346 posts ~05:00 CT (~10-11 UTC); we open the
# window a little after and keep it a few hours wide to tolerate a late posting. Outside
# it, update_recent() returns immediately. LIVE_LOOKBACK_DAYS re-checks the last few
# posted_dates so late corrections are absorbed (--resume skips those already logged).
LIVE_REFRESH_START_HOUR_UTC = 12
LIVE_REFRESH_END_HOUR_UTC = 16
LIVE_LOOKBACK_DAYS = 5


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


def backfill_range(client, conn, start: date, end: date, resume: bool) -> tuple[int, int]:
    """Ingest one document per posting date in [start, end]. Returns (docs, rows_new).

    Shared by the CLI backfill and by `update_recent`. Commits per document and never
    aborts the whole run on one bad document — the next posted_date is the retry."""
    docs = snapshot_docs(client.archive_index(PRODUCT), start, end)
    print(f"NP1-346 ingest: {len(docs)} snapshots {start} → {end}")
    n_docs = n_new = 0
    for row in docs.itertuples():
        d = row.d
        win_start, win_end = _day_window(d)
        if resume and is_completed(conn, ENDPOINT, win_start, win_end):
            continue
        try:
            df = parse_report(client.download_archive(PRODUCT, row.docId))
            n = load_resource_outages(conn, df, d)
            log_completion(conn, ENDPOINT, win_start, win_end, len(df), n)
            conn.commit()
            n_docs += 1
            n_new += n
            print(f"  [{ENDPOINT}] {d} — {len(df)} fetched, {n} new")
        except Exception as e:                           # noqa: BLE001
            conn.rollback()
            print(f"  [{ENDPOINT}] {d} — FAILED: {e}")
            traceback.print_exc(limit=2)
    return n_docs, n_new


def update_recent(client, conn) -> None:
    """Daily refresh, called by `live_updater` on every 15-minute cycle.

    Self-throttling so a once-daily archive feed is not polled at 15-minute grain:
      * outside the UTC refresh window it returns immediately (no DB, no network);
      * inside it, if today's posted_date is already in ingest_log it returns after one
        cheap lookup — so the archive is hit ~once a day (the first in-window cycle),
        then skipped for the rest of the day.
    On a genuinely missing-report day today stays unlogged and the window's cycles retry;
    that is bounded by the window width and is rare (99.8% daily density)."""
    now = datetime.now(timezone.utc)
    if not (LIVE_REFRESH_START_HOUR_UTC <= now.hour < LIVE_REFRESH_END_HOUR_UTC):
        return
    if is_completed(conn, ENDPOINT, *_day_window(now.date())):
        return
    backfill_range(client, conn, now.date() - timedelta(days=LIVE_LOOKBACK_DAYS),
                   now.date(), resume=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=date.fromisoformat, default=PANEL_START,
                   help="Inclusive posted_date start (default: panel start 2024-12-11).")
    p.add_argument("--end", type=date.fromisoformat,
                   default=datetime.now(timezone.utc).date(),
                   help="Inclusive posted_date end (default: today).")
    p.add_argument("--lookback-days", type=int, default=None,
                   help="Set start to today − N (overrides --start) for a manual "
                        "catch-up run; pair with --resume.")
    p.add_argument("--resume", action="store_true",
                   help="Skip posted_dates already logged in ingest_log.")
    args = p.parse_args(argv)
    if args.lookback_days is not None:
        args.start = datetime.now(timezone.utc).date() - timedelta(days=args.lookback_days)
    if args.start > args.end:
        sys.exit("--start must be on or before --end")

    client = ErcotClient()
    with psycopg.connect(PG_DSN) as conn:
        backfill_range(client, conn, args.start, args.end, args.resume)

    print("\nBackfill complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
