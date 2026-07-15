# live_updater.py
import argparse
import time
from datetime import datetime, timedelta, timezone

import psycopg
from ErcotClient import ErcotClient, PG_DSN
from backfill import ENDPOINTS, backfill_one_window
from backfill_dam_close import update_recent as update_forecasts
from backfill_outages import update_recent as update_outages

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
        try:
            backfill_one_window(client, conn, key, start, end, resume=False)
        except Exception as e:
            log(f"  [{key}] FAILED: {e}")
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
