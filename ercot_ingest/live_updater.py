# live_updater.py
import argparse
import time
from datetime import datetime, timedelta, timezone

import psycopg
from ErcotClient import ErcotClient, PG_DSN
from backfill import (DAILY_SETTLED, ENDPOINTS, LAGGED, backfill_one_window,
                      update_recent_daily, update_recent_lagged)
from loaders import ERCOT_TZ
from backfill_dam_close import update_recent as update_forecasts
from backfill_outages import update_recent as update_outages
from backfill_essp import update_recent as update_essp

INTERVAL_SECONDS = 900  # 15 min


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def update_recent_window(client, conn, hours_back: int = 2):
    """Pull the last `hours_back` hours for every endpoint. Idempotent. Set 2hr
    window since reports can lag; let new values from
    `ON CONFLICT DO UPDATE ... EXCLUDED.*` - overwrite for load/wind/solar since prefer recency
    """
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours_back)
    log(f"cycle start, window {start.isoformat()} → {end.isoformat()}")
    for key in ENDPOINTS:
        # Refreshed per delivery day below instead (update_recent_daily /
        # update_recent_lagged). LAGGED reports (NP6-345 load) return 0 for the
        # 2-hour "today" window and need a multi-day lookback, not this loop.
        if key in DAILY_SETTLED or key in LAGGED:
            continue
        try:
            # The vintaged wind/solar reports otherwise re-pull *every* posting
            # made so far today each cycle. Narrow them to the last `hours_back`
            # of postings — the freshest vintage, whose ~2-day look-back already
            # carries today's settled hours, matching the prefer-recency upsert.
            pw = None
            if ENDPOINTS[key].get("posting_window"):
                pw = (start.astimezone(ERCOT_TZ).strftime("%Y-%m-%dT%H:%M:%S"),
                      end.astimezone(ERCOT_TZ).strftime("%Y-%m-%dT%H:%M:%S"))
            backfill_one_window(client, conn, key, start, end, resume=False,
                                posting_window=pw)
        except Exception as e:
            log(f"  [{key}] FAILED: {e}")
            conn.rollback()
    # Day-published DAM endpoints (dam_spp, dam_shadow, dam_lambda): one lookup per
    # already-ingested day instead of re-fetching it every cycle, and pulls tomorrow
    # once past 14:00 CT.
    try:
        update_recent_daily(client, conn)
    except Exception as e:
        log(f"  [daily_settled] FAILED: {e}")
        conn.rollback()
    # Lagging daily reports (NP6-345 actual load): re-ask the last few delivery
    # days each cycle so a late publish lands instead of stalling the series.
    try:
        update_recent_lagged(client, conn)
    except Exception as e:
        log(f"  [lagged] FAILED: {e}")
        conn.rollback()
    # Vintaged load/wind/solar DAM-close forecasts (NP3-561, NP4-742/745-CD). Moved out
    # of ENDPOINTS so the hourly over-fetch stops; refreshed here at DAM-close cadence
    # instead. Self-throttling: already-logged delivery days are one cheap lookup each.
    # See backfill_dam_close.update_recent.
    try:
        update_forecasts(client, conn)
    except Exception as e:
        log(f"  [forecast_dam] FAILED: {e}")
        conn.rollback()
    # NP1-346 unplanned resource outages — a once-daily archive feed folded into this
    # single cron. Self-throttling: on most cycles this is one ingest_log lookup and
    # returns; it hits the archive ~once a day. See backfill_outages.update_recent.
    try:
        update_outages(client, conn)
    except Exception as e:
        log(f"  [resource_outages] FAILED: {e}")
        conn.rollback()
    # NP4-158-SG ESSP — a twice-daily archive feed (pre-DAM study + post-DAM final),
    # same self-throttle: a delivery day with both vintages already logged is skipped
    # with no network. See backfill_essp.update_recent.
    try:
        update_essp(client, conn)
    except Exception as e:
        log(f"  [essp] FAILED: {e}")
        conn.rollback()
    log("cycle complete")


def run_once() -> None:
    """Single cycle. Raises on connection failure so caller can fail fast."""
    client = ErcotClient()
    with psycopg.connect(PG_DSN) as conn:
        update_recent_window(client, conn)


def run_forever() -> None:
    """Loop forever, sleeping between cycles. Used by docker-compose."""
    client = ErcotClient()
    print("Live updater started. Polling every 15 min.")
    while True:
        try:
            with psycopg.connect(PG_DSN) as conn:
                update_recent_window(client, conn)
        except Exception as e:
            print(f"Cycle failed: {e}")
        time.sleep(INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single update cycle and exit. Used by k8s CronJob.",
    )
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_forever()


if __name__ == "__main__":
    main()
