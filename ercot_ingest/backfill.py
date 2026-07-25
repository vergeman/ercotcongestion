"""
Backfill ERCOT public reports over a date range.

Usage:
    docker compose run --rm compute
    python /ercot_ingest/backfill.py --start 2026-02-23 --end 2026-04-23
    python /ercot_ingest/backfill.py --start 2026-02-23 --end 2026-04-23 --endpoint dam_shadow
    python /ercot_ingest/backfill.py --start 2026-02-23 --end 2026-04-23 --resume

Chunks by day. Idempotent: re-running skips completed (endpoint, day) pairs.
"""
import argparse
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import psycopg

from ErcotClient import ErcotClient, PG_DSN
# ERCOT_TZ: ERCOT's public API interprets naive timestamp filters in Central
# Time. Sending UTC made the live window land ~5h in the future and return 0
# rows.
from loaders import (ERCOT_TZ,
                     load_zonal_lmp, load_outages,
                     load_load_by_zone, load_wind_hourly, load_solar_hourly,
                     load_dam_spp, load_dam_shadow_prices, load_dam_lambda,
                     load_sced_lambda)


ENDPOINTS = {
    "zonal_lmp": {
        "path": "/np6-905-cd/spp_node_zone_hub",
        "loader": load_zonal_lmp,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
        "extra_params": {"settlementPointType": "HU"}
    },
    "outages": {
        "path": "/np3-233-cd/hourly_res_outage_cap",
        "loader": load_outages,
        "from_param": "postedDatetimeFrom",
        "to_param": "postedDatetimeTo",
        "param_format": "datetime",
    },
    "loads": {
        "path": "/np6-345-cd/act_sys_load_by_wzn",
        "loader": load_load_by_zone,
        "from_param": "operatingDayFrom",
        "to_param": "operatingDayTo",
        "param_format": "date",  # yyyy-MM-dd
    },
    # wind/solar are a rolling actual+forecast report republished ~hourly, so a
    # whole-day deliveryDate query returns day D's 24 hours from every one of the
    # ~215 vintages whose window overlapped D (~5,180 rows) — of which the loader
    # keeps only the newest per hour. `posting_window: True` tells callers to
    # narrow the fetch to a single settled vintage (see settled_posting_window).
    "wind": {
        "path": "/np4-742-cd/wpp_hrly_actual_fcast_geo",
        "loader": load_wind_hourly,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
        "posting_window": True,
    },
    "solar": {
        "path": "/np4-745-cd/spp_hrly_actual_fcast_geo",
        "loader": load_solar_hourly,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
        "posting_window": True,
    },
    "dam_spp": {
        "path": "/np4-190-cd/dam_stlmnt_pnt_prices",
        "loader": load_dam_spp,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
    },
    "dam_shadow": {
        "path": "/np4-191-cd/dam_shadow_prices",
        "loader": load_dam_shadow_prices,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
    },
    "dam_lambda": {
        "path": "/np4-523-cd/dam_system_lambda",
        "loader": load_dam_lambda,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
    },
    "sced_lambda": {
        "path": "/np6-322-cd/sced_system_lambda",
        "loader": load_sced_lambda,
        "from_param": "SCEDTimestampFrom",
        "to_param": "SCEDTimestampTo",
        "param_format": "datetime",
    },
    # The vintaged forecasts (load NP3-561-CD, wind NP4-742-CD, solar NP4-745-CD) are
    # deliberately NOT ingested here. Fetched by posting time over a whole-day window,
    # those endpoints return *every* publication — ~24 vintages a day — but the model
    # only ever reads the single one admissible at DAM close. They belong to
    # `backfill_dam_close.py`, which keeps exactly one vintage per delivery day, and
    # whose `update_recent()` `live_updater` calls each cycle to stay fresh. Carrying
    # them here made both a bulk `backfill.py` run and every live cycle pull the other
    # 23 postings for nothing.
}

def is_completed(conn, endpoint: str, start: datetime, end: datetime) -> bool:
    # A 0-row fetch usually means the source hadn't published yet (e.g. an
    # in-progress operating day), not that the window is done — so --resume
    # retries those instead of skipping them forever.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ingest_log WHERE endpoint = %s AND window_start = %s "
            "AND window_end = %s AND rows_fetched > 0",
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


def settled_posting_window(delivery_day: date) -> tuple[str, str]:
    """CT posting window for the morning after `delivery_day`.

    For the rolling wind/solar actual+forecast reports (NP4-742/745). Any vintage
    published that morning already carries all of day D's realized hours in its
    ~2-day look-back (measured median posted−interval lag +48.9h), settled and
    complete — verified against the live API on a normal day and both DST
    transitions, where a 2h slice returns the identical interval set as the
    full-day query (23 hours on spring-forward, 25 with the DSTFlag duplicate on
    fall-back).

    The window is widened to 04:00–10:00 CT (~6 hourly postings) purely for
    resilience: any single posting suffices, so spanning six of them means a
    missed publication or two never leaves a day empty. Still one 1000-row page
    (~6 vintages × 24h ≈ 145 rows) and the loaders' keep="last" dedup collapses it
    to one vintage anyway — so this cuts the daily fetch from ~5,180 rows to ~145
    without the fragility of a two-hour slot. ERCOT reads naive datetime filters
    as CT, so no tz suffix.
    """
    nxt = delivery_day + timedelta(days=1)
    return (nxt.strftime("%Y-%m-%dT04:00:00"), nxt.strftime("%Y-%m-%dT10:00:00"))


def daily_windows(start_date: date, end_date: date):
    """Yield (start_dt, end_dt) UTC datetimes for each day [start_date, end_date]."""
    d = start_date
    while d <= end_date:
        start_dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(days=1)
        yield start_dt, end_dt
        d += timedelta(days=1)


def backfill_one_window(client: ErcotClient, conn, endpoint_key: str,
                        start: datetime, end: datetime, resume: bool,
                        posting_window: tuple[str, str] | None = None) -> None:
    cfg = ENDPOINTS[endpoint_key]

    if resume and is_completed(conn, endpoint_key, start, end):
        print(f"  [{endpoint_key}] {start.date()} — skip (already done)")
        return

    if cfg["param_format"] == "date":
        # 'date' filters are inclusive on both ends and operate on whole days.
        # ERCOT treats the date string as a CT day; pass through the user-supplied
        # date label without TZ conversion so CLI intent matches.
        from_value = start.strftime("%Y-%m-%d")
        to_value = (end - timedelta(seconds=1)).strftime("%Y-%m-%d")
    else:
        # ERCOT interprets naive datetime filters as CT.
        from_value = start.astimezone(ERCOT_TZ).strftime("%Y-%m-%dT%H:%M:%S")
        to_value = end.astimezone(ERCOT_TZ).strftime("%Y-%m-%dT%H:%M:%S")

    params = {
        cfg["from_param"]: from_value,
        cfg["to_param"]: to_value,
        **cfg.get("extra_params", {}),
    }
    # Narrow the vintaged wind/solar reports to a single posting (see the
    # `posting_window` note on those ENDPOINTS entries). The (interval_ts,
    # dst_flag) upsert and the loaders' keep="last" dedup both stay correct with
    # one vintage; the ingest_log window key is unchanged, so --resume is unaffected.
    if posting_window is not None:
        params["postedDatetimeFrom"], params["postedDatetimeTo"] = posting_window

    df = client.get(cfg["path"], **params)

    rows_fetched = len(df)
    rows_inserted = cfg["loader"](conn, df)
    log_completion(conn, endpoint_key, start, end, rows_fetched, rows_inserted)
    conn.commit()

    print(f"  [{endpoint_key}] {start.date()} — {rows_fetched} fetched, {rows_inserted} new")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC), inclusive")
    parser.add_argument("--endpoint",
                        choices=[*ENDPOINTS, "all"],
                        default="all")
    parser.add_argument("--resume", action="store_true",
                        help="Skip windows already in ingest_log")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    if start_date > end_date:
        sys.exit("--start must be on or before --end")

    keys = list(ENDPOINTS.keys()) if args.endpoint == "all" else [args.endpoint]

    client = ErcotClient()

    with psycopg.connect(PG_DSN) as conn:
        total_days = (end_date - start_date).days + 1
        print(f"Backfilling {keys} for {total_days} days: {start_date} → {end_date}")

        for start, end in daily_windows(start_date, end_date):
            for key in keys:
                try:
                    pw = (settled_posting_window(start.date())
                          if ENDPOINTS[key].get("posting_window") else None)
                    backfill_one_window(client, conn, key, start, end,
                                        args.resume, posting_window=pw)
                except Exception as e:
                    print(f"  [{key}] {start.date()} — FAILED: {e}")
                    traceback.print_exc(limit=2)
                    conn.rollback()
                    # The rollback also discards the window's ingest_log insert,
                    # which is how failed days used to vanish without a trace
                    # while every other endpoint logged success. Commit a -1
                    # marker so the failure is visible; rows_fetched <= 0 keeps
                    # it retryable under --resume.
                    try:
                        log_completion(conn, key, start, end, -1, -1)
                        conn.commit()
                    except Exception:
                        conn.rollback()  # connection may be unusable; keep going
                    # continue to next window — don't abort entire run

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
