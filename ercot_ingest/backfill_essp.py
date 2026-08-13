"""Backfill NP4-158-SG DAM Electrically Similar Settlement Points over a delivery-date range.

plan/0129-0008. NP4-158-SG is an ARCHIVE product — a zip wrapping one CSV — published
TWICE per delivery day: a pre-06:00 study and a post-DAM final, both posted on D-1 and
both describing delivery day D. It therefore fits neither `backfill.py`'s JSON `ENDPOINTS`
table (delivery-date filters, paged JSON) nor its `client.get`. Like `backfill_outages.py`
it is its own driver, launchable as a Job:

    python /ercot_ingest/backfill_essp.py --start 2025-01-01 --end 2026-08-13 --resume

Pipeline: `ErcotClient.archive_index` filtered to the D-1 posting day → the latest study
and the latest final for that day (`_select_vintages`) → `download_archive` →
`_read_csv_zip` (unzip + CSV) → `loaders.load_essp` with `is_study` set per vintage.
Transport-only lives in the client; the unzip/parse is here, matching the NP1-346 split.

The two vintages are retained as SEPARATE `ingest_log` endpoints (`essp_study`,
`essp_final`) and separate `is_study` rows — the forecast-only brief reads the study, the
settled view reads the final; they are labelled vintages, not revisions to overwrite.
Idempotent: `--resume` skips (endpoint, delivery-day) pairs already in `ingest_log`, and
the loader's ON CONFLICT DO UPDATE absorbs re-runs.

Recurring ingest reuses this driver, folded into the single 15-minute `ercot-ingest` cron:
`live_updater` calls `update_recent()` each cycle, which is self-throttling (a delivery
day whose study AND final are both already logged is skipped with no network) so this
twice-daily feed is fetched about twice a day, not every 15 minutes.
"""
import argparse
import io
import sys
import traceback
import zipfile
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import psycopg

from backfill import is_completed, log_completion   # shared ingest_log semantics
from ErcotClient import PG_DSN, ErcotClient
from loaders import ERCOT_TZ, load_essp

PRODUCT = "np4-158-sg"
ENDPOINT_STUDY = "essp_study"
ENDPOINT_FINAL = "essp_final"

# The study posts ~05:55 CT and the final after the DAM clears (~13:00 CT). Split the
# posting day's documents at this ERCOT-local hour; within each side the latest posting
# (a correction) wins.
STUDY_BEFORE_HOUR_CT = 10

# ERCOT publishes delivery day D on D-1, so the posting day is one day behind the
# delivery-date window that keys ingest_log.
POSTED_DAY_OFFSET = timedelta(days=-1)

DELIVERY_DATE_COLUMN = "DeliveryDate"

# Backfill default — the brief needs the grouping from the start of the served window.
PANEL_START = date(2025, 1, 1)

# live_updater re-checks the last few delivery days each cycle so a late study or final
# lands when it posts; --resume skips those already logged. A delivery day leads the
# clock (D published on D-1), so update_recent reaches D+1.
LIVE_LOOKBACK_DAYS = 3


def _day_window(d: date) -> tuple[datetime, datetime]:
    """The [00:00, +1d) UTC window that keys this delivery day in ingest_log."""
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _read_csv_zip(blob: bytes) -> pd.DataFrame:
    """The single CSV inside an archive document's zip. Raises if it is not exactly one."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        csvs = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(csvs) != 1:
            raise ValueError(f"expected one CSV in {PRODUCT} archive document, found {csvs}")
        return pd.read_csv(archive.open(csvs[0]))


def _select_vintages(docs: pd.DataFrame) -> list[tuple[str, object]]:
    """(endpoint, doc-row) for the latest study and the latest final in a posting day.

    Documents split by ERCOT-local posting hour at STUDY_BEFORE_HOUR_CT: the pre-DAM
    study posts before it, the final after. Within each side the newest posting wins, so
    a correction supersedes the report it corrects. Either side may be absent (a day
    read before the DAM clears has a study but no final yet)."""
    if docs.empty:
        return []
    docs = docs.copy()
    docs["hour"] = docs["posted"].dt.hour
    selected = []
    for endpoint, mask in ((ENDPOINT_STUDY, docs["hour"] < STUDY_BEFORE_HOUR_CT),
                           (ENDPOINT_FINAL, docs["hour"] >= STUDY_BEFORE_HOUR_CT)):
        matches = docs[mask]
        if not matches.empty:
            selected.append((endpoint, matches.sort_values("posted").iloc[-1]))
    return selected


def _posting_day_docs(client: ErcotClient, posted_day: date) -> pd.DataFrame:
    """CSV archive documents posted on `posted_day` (XML companions filtered out)."""
    docs = client.archive_index(PRODUCT, posted_day=posted_day)
    if docs.empty:
        return docs
    return docs[docs["friendlyName"].str.contains("csv", case=False, na=False)]


def ingest_delivery_day(client: ErcotClient, conn, delivery_day: date,
                        resume: bool) -> tuple[int, int]:
    """Ingest the study and final for one delivery day. Returns (vintages, rows_new).

    Self-throttle: under --resume, if both vintages are already logged this returns
    immediately with no network. Commits per vintage; a bad vintage does not block the
    other."""
    win = _day_window(delivery_day)
    if resume and all(is_completed(conn, ep, *win)
                      for ep in (ENDPOINT_STUDY, ENDPOINT_FINAL)):
        return 0, 0

    posted_day = delivery_day + POSTED_DAY_OFFSET
    vintages = _select_vintages(_posting_day_docs(client, posted_day))
    n_vint = n_new = 0
    for endpoint, doc in vintages:
        if resume and is_completed(conn, endpoint, *win):
            continue
        try:
            df = _read_csv_zip(client.download_archive(PRODUCT, int(doc.docId)))
            dates = pd.to_datetime(df[DELIVERY_DATE_COLUMN]).dt.date.unique()
            if len(dates) != 1 or dates[0] != delivery_day:
                raise ValueError(
                    f"document {doc.docId} describes {dates}, expected {delivery_day}")
            n = load_essp(conn, df, is_study=(endpoint == ENDPOINT_STUDY))
            log_completion(conn, endpoint, *win, len(df), n)
            conn.commit()
            n_vint += 1
            n_new += n
            print(f"  [{endpoint}] {delivery_day} — {len(df)} fetched, {n} new")
        except Exception as e:                           # noqa: BLE001
            conn.rollback()
            print(f"  [{endpoint}] {delivery_day} — FAILED: {e}")
            traceback.print_exc(limit=2)
    return n_vint, n_new


def backfill_range(client, conn, start: date, end: date, resume: bool) -> tuple[int, int]:
    """Ingest both vintages for each delivery day in [start, end]. Returns (vintages, rows_new).

    Shared by the CLI backfill and by `update_recent`."""
    print(f"NP4-158-SG ingest: delivery days {start} → {end}")
    n_vint = n_new = 0
    d = start
    while d <= end:
        v, n = ingest_delivery_day(client, conn, d, resume)
        n_vint += v
        n_new += n
        d += timedelta(days=1)
    return n_vint, n_new


def update_recent(client, conn) -> None:
    """Daily refresh, called by `live_updater` on every 15-minute cycle.

    Self-throttling: a delivery day whose study and final are both already in
    `ingest_log` is skipped before any network call (see `ingest_delivery_day`), so on a
    steady state this touches the archive only for the days still missing a vintage — the
    next-day study before ~06:00 CT and its final before the DAM clears. Reaches D+1
    because delivery day D publishes on D-1."""
    today = datetime.now(timezone.utc).astimezone(ERCOT_TZ).date()
    backfill_range(client, conn, today - timedelta(days=LIVE_LOOKBACK_DAYS),
                   today + timedelta(days=1), resume=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=date.fromisoformat, default=PANEL_START,
                   help="Inclusive delivery-date start (default: panel start 2025-01-01).")
    p.add_argument("--end", type=date.fromisoformat,
                   default=datetime.now(timezone.utc).astimezone(ERCOT_TZ).date(),
                   help="Inclusive delivery-date end (default: today CT).")
    p.add_argument("--lookback-days", type=int, default=None,
                   help="Set start to today − N (overrides --start) for a manual "
                        "catch-up run; pair with --resume.")
    p.add_argument("--resume", action="store_true",
                   help="Skip (endpoint, delivery-day) pairs already logged in ingest_log.")
    args = p.parse_args(argv)
    if args.lookback_days is not None:
        args.start = (datetime.now(timezone.utc).astimezone(ERCOT_TZ).date()
                      - timedelta(days=args.lookback_days))
    if args.start > args.end:
        sys.exit("--start must be on or before --end")

    client = ErcotClient()
    with psycopg.connect(PG_DSN) as conn:
        backfill_range(client, conn, args.start, args.end, args.resume)

    print("\nBackfill complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
