"""Backfill the forecast vintage that was on the table at DAM close.

plan/0085 commit 2. The mu-model predicts, at DAM close on day D-1, what will
bind during day D. So the ONLY admissible covariate vintage is the last one
ERCOT published before that moment. This script fetches exactly that vintage —
one publication per delivery day, not all ~24 — which is why a ~570-day backfill
of three products is ~1,700 API calls rather than ~41,000.

WHY IT IS NEEDED. The existing tables cannot answer the question:

  * ``wind_hourly_regional`` / ``solar_hourly_regional`` keep one row per hour,
    overwritten by the latest posting. Measured median ``posted - interval`` lag:
    **+48.9h**. **0.0%** of stored rows were published before the DAM close of
    the hour they describe. They hold actuals, not forecasts.
  * ``load_forecast_zonal`` *is* vintaged, but only reaches back to **2026-03-26**
    — 15 of the 46 scored weeks.

Both are backfilled here, into `wind_forecast_regional` / `solar_forecast_regional`
(migration 26) and `load_forecast_zonal` respectively.

THE LEAK GUARD IS STRUCTURAL, NOT ADVISORY. Only rows with
``deliveryDate >= D`` are kept — the forward view as of DAM close. Every such row
is for an hour that had not happened when the vintage was published, so its
``gen_*`` (realized generation) must be NULL. Migration 26's CHECK constraint
enforces that, so a vintage mix-up aborts the insert instead of quietly becoming
model skill. Verified against the live API: in the 2025-08-01T09:55 CT posting,
delivery day 2025-08-02 has 24/24 forecast values and 0/24 actuals.

    docker compose run --rm compute python /ercot_ingest/backfill_dam_close.py \
        --start 2024-12-01 --end 2026-07-01 --resume
"""
import argparse
import io
import os
import sys
import traceback
import zipfile
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import psycopg

from backfill import is_completed, log_completion
from ErcotClient import BASE_URL, ErcotClient, PG_DSN
from loaders import (ERCOT_TZ, load_load_forecast, load_solar_forecast,
                     load_wind_forecast)

# ERCOT's Day-Ahead Market closes at 10:00 Central on the day before delivery.
# Everything this project forecasts is conditioned on that instant.
DAM_CLOSE_HOUR = 10

# How far back before DAM close to look for a publication. The products post
# hourly (wind/solar at ~:55, load forecast at ~:30), so 2h reliably contains at
# least one posting and — at ERCOT's 1000-row page size — keeps wind/solar to a
# single page (a 5h window returns ~1080 rows and costs a second round-trip on
# EVERY day of the backfill).
#
# If a publication really was missed, fall back to the wide window rather than
# leaving the day with no covariates at all. Always take the LATEST vintage at or
# before DAM close: the most recent thing a bidder could have known.
LOOKBACK_HOURS = 2
LOOKBACK_HOURS_FALLBACK = 8

PRODUCTS = {
    "load_forecast_dam": {
        "path": "/np3-561-cd/7d_load_fcast_by_wzn",
        "loader": load_load_forecast,
        # NP3-561's *data* endpoint only retains ~3-4 months (measured: serves
        # 2026-04-01, empty at 2026-03-01 — which is exactly why
        # `load_forecast_zonal` began at 2026-03-26 and covered just 15 of the 46
        # scored weeks). Everything older exists only as archived zips. Wind and
        # solar have no such limit (measured back to 2024-06), so only this
        # product needs the fallback.
        "archive_emil": "np3-561-cd",
    },
    "wind_forecast_dam": {
        "path": "/np4-742-cd/wpp_hrly_actual_fcast_geo",
        "loader": load_wind_forecast,
    },
    "solar_forecast_dam": {
        "path": "/np4-745-cd/spp_hrly_actual_fcast_geo",
        "loader": load_solar_forecast,
    },
}

# Archive CSVs are not the JSON API in another coat: different column names,
# US-format dates, and DSTFlag as 'Y'/'N'. That last one is a live trap — the
# loader does `bool(r["DSTFlag"])`, and `bool("N") is True`, so an unmapped
# passthrough would silently mark every row DST and shift its interval_ts.
_LOAD_CSV_TO_API = {
    "DeliveryDate": "deliveryDate", "HourEnding": "hourEnding",
    "Coast": "coast", "East": "east", "FarWest": "farWest", "North": "north",
    "NorthCentral": "northCentral", "SouthCentral": "southCentral",
    "Southern": "southern", "West": "west", "SystemTotal": "systemTotal",
}


def fetch_archive_vintage(client: ErcotClient, emil: str,
                          lo: datetime, hi: datetime) -> pd.DataFrame:
    """Fetch the newest archived publication in [lo, hi) and return it API-shaped.

    Used only when the data endpoint has aged the vintage out. The archive keeps
    everything, so this is what makes the pre-2026-03 load forecast reachable at
    all.
    """
    headers = {"Authorization": f"Bearer {client._get_token()}",
               "Ocp-Apim-Subscription-Key": os.environ["ERCOT_SUBSCRIPTION_KEY"]}
    url = f"{BASE_URL}/archive/{emil}"

    # _request carries the throttle and the 429/5xx retry loop (and sets its own
    # timeout) — going around it would get this backfill rate-limited off.
    listing = client._request("GET", url, headers=headers, params={
        "postDatetimeFrom": lo.strftime("%Y-%m-%dT%H:%M:%S"),
        "postDatetimeTo": hi.strftime("%Y-%m-%dT%H:%M:%S")}).json()

    docs = listing.get("archives", [])
    if not docs:
        return pd.DataFrame()

    newest = max(docs, key=lambda d: d["postDatetime"])
    blob = client._request("GET", url, headers=headers,
                           params={"download": newest["docId"]}).content

    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = pd.read_csv(z.open(z.namelist()[0]))

    df = raw.rename(columns=_LOAD_CSV_TO_API)
    df["DSTFlag"] = raw["DSTFlag"].map({"Y": True, "N": False}).fillna(False)
    df["postedDatetime"] = newest["postDatetime"]
    return df


def dam_close_window(delivery_day: date,
                     hours: int = LOOKBACK_HOURS) -> tuple[datetime, datetime]:
    """The publication window to search for delivery day D, in ERCOT-local time.

    Returns ``[D-1 (10:00 - hours), D-1 10:00)``. Naive datetimes: the ERCOT API
    interprets timestamp filters as Central, which is why `backfill.py` converts
    rather than sending UTC.

    The upper bound is DAM close itself and is the load-bearing part: it is what
    makes every row in these tables something a bidder could actually have known.
    """
    close = datetime(delivery_day.year, delivery_day.month, delivery_day.day,
                     DAM_CLOSE_HOUR) - timedelta(days=1)
    return close - timedelta(hours=hours), close


def latest_vintage(df: pd.DataFrame, delivery_day: date) -> pd.DataFrame:
    """Keep only the newest publication, and only its forward view.

    Two filters, and both are load-bearing:

    * ``postedDatetime == max`` — a window may span several publications. Mixing
      them would put two different beliefs in one feature row.
    * ``deliveryDate >= D`` — drop the vintage's backward view (recent hours, for
      which it carries realized ``gen_*``). Those are legitimately known at DAM
      close, but they are *actuals*, they belong in the actuals tables, and
      keeping them here is how a "forecast" table quietly acquires a lookahead.
    """
    if df.empty:
        return df
    newest = df["postedDatetime"].max()
    keep = (df["postedDatetime"] == newest) & (
        pd.to_datetime(df["deliveryDate"]).dt.date >= delivery_day)
    return df[keep]


def _fetch(client: ErcotClient, cfg: dict, lo: datetime, hi: datetime
           ) -> tuple[pd.DataFrame, str]:
    """One window, data endpoint first and the archive only if it comes back dry."""
    df = client.get(cfg["path"],
                    postedDatetimeFrom=lo.strftime("%Y-%m-%dT%H:%M:%S"),
                    postedDatetimeTo=hi.strftime("%Y-%m-%dT%H:%M:%S"))
    if df.empty and cfg.get("archive_emil"):
        return fetch_archive_vintage(client, cfg["archive_emil"], lo, hi), "archive"
    return df, "api"


def backfill_one_day(client: ErcotClient, conn, key: str, delivery_day: date,
                     resume: bool) -> None:
    cfg = PRODUCTS[key]
    lo, hi = dam_close_window(delivery_day)
    lo_utc = lo.replace(tzinfo=ERCOT_TZ).astimezone(timezone.utc)
    hi_utc = hi.replace(tzinfo=ERCOT_TZ).astimezone(timezone.utc)

    if resume and is_completed(conn, key, lo_utc, hi_utc):
        print(f"  [{key}] {delivery_day} — skip (done)")
        return

    df, source = _fetch(client, cfg, lo, hi)
    vintage = latest_vintage(df, delivery_day)

    if vintage.empty:
        # The narrow window found nothing. Before giving up on the day, look
        # further back: a missed publication is not a reason to leave the model
        # blind, as long as we still stop at DAM close.
        wide_lo, _ = dam_close_window(delivery_day, LOOKBACK_HOURS_FALLBACK)
        df, source = _fetch(client, cfg, wide_lo, hi)
        vintage = latest_vintage(df, delivery_day)
        source += "/wide"

    fetched = len(df)
    if vintage.empty:
        # Not fatal — but never silent. A gap here is a day the model has no
        # covariates for, and features.py must see it as missing rather than
        # inherit a neighbour's forecast.
        print(f"  [{key}] {delivery_day} — NO VINTAGE even in "
              f"{LOOKBACK_HOURS_FALLBACK}h window before DAM close "
              f"({fetched} rows fetched)")
        return

    posted = vintage["postedDatetime"].iloc[0]
    inserted = cfg["loader"](conn, vintage)
    log_completion(conn, key, lo_utc, hi_utc, fetched, inserted)
    conn.commit()
    print(f"  [{key}] {delivery_day} — {source} vintage {posted} → "
          f"{len(vintage)} rows kept of {fetched}, {inserted} new")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="first DELIVERY day, YYYY-MM-DD")
    p.add_argument("--end", required=True, help="last DELIVERY day, inclusive")
    p.add_argument("--product", choices=[*PRODUCTS, "all"], default="all")
    p.add_argument("--resume", action="store_true",
                   help="skip (product, day) pairs already in ingest_log")
    args = p.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start > end:
        sys.exit("--start must be on or before --end")

    keys = list(PRODUCTS) if args.product == "all" else [args.product]
    days = (end - start).days + 1
    print(f"DAM-close vintages: {keys} × {days} delivery days "
          f"{start} → {end}  (~{len(keys) * days} API calls)")

    client = ErcotClient()
    misses = 0
    conn = psycopg.connect(PG_DSN)
    try:
        for i in range(days):
            d = start + timedelta(days=i)
            for key in keys:
                try:
                    backfill_one_day(client, conn, key, d, args.resume)
                except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                    # This run holds one connection for hours, and the database
                    # restarted underneath an earlier attempt — after which every
                    # remaining day failed against a dead handle, turning a
                    # transient blip into a wasted run. Reconnect and retry the
                    # day once. `--resume` makes the retry cheap and the whole
                    # script restartable, but only if we get this far.
                    print(f"  [{key}] {d} — connection lost ({e}); reconnecting")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = psycopg.connect(PG_DSN)
                    try:
                        backfill_one_day(client, conn, key, d, args.resume)
                    except Exception as retry_err:
                        misses += 1
                        print(f"  [{key}] {d} — FAILED after reconnect: {retry_err}")
                        conn.rollback()
                except Exception as e:
                    misses += 1
                    print(f"  [{key}] {d} — FAILED: {e}")
                    traceback.print_exc(limit=2)
                    conn.rollback()
    finally:
        conn.close()

    print(f"\nDone. {misses} failures.")


if __name__ == "__main__":
    main()
