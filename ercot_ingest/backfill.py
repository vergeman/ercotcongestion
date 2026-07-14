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
                     load_sced_lambda, load_load_forecast,
                     load_wind_forecast, load_solar_forecast)


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
    "wind": {
        "path": "/np4-742-cd/wpp_hrly_actual_fcast_geo",
        "loader": load_wind_hourly,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
    },
    "solar": {
        "path": "/np4-745-cd/spp_hrly_actual_fcast_geo",
        "loader": load_solar_hourly,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
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
    "load_forecast": {
        "path": "/np3-561-cd/7d_load_fcast_by_wzn",
        "loader": load_load_forecast,
        "from_param": "postedDatetimeFrom",
        "to_param": "postedDatetimeTo",
        "param_format": "datetime",
    },
    # The same two products as `wind` / `solar` above, fetched by POSTING time
    # rather than delivery date and written to the vintaged tables (migration 26)
    # instead of the actuals tables. Both are needed and they are not redundant:
    #
    #   wind / solar          -> what the hour turned out to be   (actuals)
    #   wind_forecast / solar_forecast -> what was believed, and WHEN (vintages)
    #
    # The actuals loaders dedup to the most recent posting, which is why they can
    # never answer "what did we know at DAM close?" — the surviving row is the one
    # published ~2 days later. Keep these entries in ENDPOINTS so `live_updater`
    # picks them up on its normal cycle: without them, the vintaged tables stop
    # accumulating the moment the backfill's end date passes, and the mu-model's
    # covariates silently go stale.
    "wind_forecast": {
        "path": "/np4-742-cd/wpp_hrly_actual_fcast_geo",
        "loader": load_wind_forecast,
        "from_param": "postedDatetimeFrom",
        "to_param": "postedDatetimeTo",
        "param_format": "datetime",
    },
    "solar_forecast": {
        "path": "/np4-745-cd/spp_hrly_actual_fcast_geo",
        "loader": load_solar_forecast,
        "from_param": "postedDatetimeFrom",
        "to_param": "postedDatetimeTo",
        "param_format": "datetime",
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

    df = client.get(cfg["path"], **{
        cfg["from_param"]: from_value,
        cfg["to_param"]: to_value,
        **cfg.get("extra_params", {})
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
                    backfill_one_window(client, conn, key, start, end, args.resume)
                except Exception as e:
                    print(f"  [{key}] {start.date()} — FAILED: {e}")
                    traceback.print_exc(limit=2)
                    conn.rollback()
                    # continue to next window — don't abort entire run

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
