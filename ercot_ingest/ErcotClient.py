"""
Ingest a recent window of ERCOT public reports into Postgres.
Idempotent: re-running same window inserts zero new rows.
"""
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg
import requests

from shared.settings import settings

from dotenv import load_dotenv
from psycopg.rows import dict_row

from loaders import (ERCOT_TZ,
                     load_outages,
                     load_dam_spp, load_dam_shadow_prices, load_dam_lambda,
                     load_sced_lambda, load_load_forecast,
                     print_recent_outages)

load_dotenv()

USERNAME = os.environ["ERCOT_USERNAME"]
PASSWORD = os.environ["ERCOT_PASSWORD"]
SUB_KEY = os.environ["ERCOT_SUBSCRIPTION_KEY"]
PROXY_BASE = os.environ["PROXY_BASE"]
PROXY_SECRET = os.environ["WRANGLER_PROXY_SECRET"]
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"

# Route through the Cloudflare Worker. The Worker maps:
#   /token/* → https://ercotb2c.b2clogin.com/*
#   /api/*   → https://api.ercot.com/*
TOKEN_URL = (
    f"{PROXY_BASE}/token/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
BASE_URL = f"{PROXY_BASE}/api/public-reports"

PG_DSN = settings.pg_dsn


class ErcotClient:
    def __init__(self, min_interval: float = 3.0, max_retries: int = 5):
        self._token = None
        self._exp = 0
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers["X-Proxy-Auth"] = PROXY_SECRET

    def _throttle(self):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        match = re.search(r"Try again in (\d+)", response.text or "")
        if match:
            return float(match.group(1)) + 1  # +1s buffer
        return 60.0

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        for attempt in range(self._max_retries):
            self._throttle()
            response = self._session.request(method, url, timeout=60, **kwargs)

            if response.status_code == 429:
                wait = self._parse_retry_after(response)
                print(f"  HTTP 429, waiting {wait:.1f}s (server-requested)")
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"  HTTP {response.status_code}, retry {attempt+1}/{self._max_retries} in {wait:.1f}s")
                time.sleep(wait)
                continue

            return response
        return response  # last response, even if still failing

    def _get_token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        response = self._request(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "password",
                "username": USERNAME,
                "password": PASSWORD,
                "scope": f"openid {CLIENT_ID} offline_access",
                "client_id": CLIENT_ID,
                "response_type": "id_token",
            },
        )
        response.raise_for_status()
        body = response.json()
        self._token = body["id_token"]
        self._exp = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def get(self, endpoint, **params):
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Ocp-Apim-Subscription-Key": SUB_KEY,
        }
        url = f"{BASE_URL}{endpoint}"
        rows, fields, page = [], None, 1
        while True:
            response = self._request(
                "GET", url, headers=headers,
                params={**params, "page": page, "size": 1000},
            )
            if response.status_code >= 400:
                print(f"HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()

            payload = response.json()
            if fields is None:
                fields = [field["name"] for field in payload.get("fields", [])]
            rows.extend(payload.get("data", []))

            total_pages = payload.get("_meta", {}).get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

        return pd.DataFrame(rows, columns=fields) if fields else pd.DataFrame()

#
# MAIN
#

def main():
    end = datetime.now(timezone.utc) - timedelta(days=2)
    end = end.replace(hour=22, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=1)
    # ERCOT's API interprets naive datetime filters as Central Time.
    iso_from = start.astimezone(ERCOT_TZ).strftime("%Y-%m-%dT%H:%M:%S")
    iso_to = end.astimezone(ERCOT_TZ).strftime("%Y-%m-%dT%H:%M:%S")

    date_from = start.strftime("%Y-%m-%d")
    date_to = end.strftime("%Y-%m-%d")
    hour_from = start.hour
    hour_to = end.hour
    print(f"Window: {iso_from} → {iso_to}")

    client = ErcotClient()

    #
    # Zonal LMP
    #

    print("\nFetching NP6-905-CD")
    zonal_lmp = client.get(
        "/np6-905-cd/spp_node_zone_hub",
        deliveryDateFrom=date_from, deliveryDateTo=date_to,
        #deliveryHourFrom=hour_from, deliveryHourTo=hour_to,
        settlementPointType="HU"  # filter to relevant hubs
    )
    print(f"  {len(zonal_lmp)} rows")

    #
    # Outages
    #

    print("Fetching NP3-233-CD…")
    outages = client.get(
        "/np3-233-cd/hourly_res_outage_cap",
        postedDatetimeFrom=iso_from, postedDatetimeTo=iso_to,
    )
    print(f"  {len(outages)} rows")

    #
    # DAM SPP
    #

    print("\nFetching NP4-190-CD…")
    dam_spp = client.get(
        "/np4-190-cd/dam_stlmnt_pnt_prices",
        deliveryDateFrom=date_from, deliveryDateTo=date_to,
    )
    print(f"  {len(dam_spp)} rows")

    #
    # DAM Shadow Prices
    #

    print("\nFetching NP4-191-CD…")
    dam_shadow = client.get(
        "/np4-191-cd/dam_shadow_prices",
        deliveryDateFrom=date_from, deliveryDateTo=date_to,
    )
    print(f"  {len(dam_shadow)} rows")

    #
    # DAM System Lambda
    #

    print("\nFetching NP4-523-CD…")
    dam_lambda = client.get(
        "/np4-523-cd/dam_system_lambda",
        deliveryDateFrom=date_from, deliveryDateTo=date_to,
    )
    print(f"  {len(dam_lambda)} rows")

    #
    # SCED System Lambda
    #

    print("\nFetching NP6-322-CD…")
    sced_lambda = client.get(
        "/np6-322-cd/sced_system_lambda",
        SCEDTimestampFrom=iso_from, SCEDTimestampTo=iso_to,
    )
    print(f"  {len(sced_lambda)} rows")

    #
    # 7-Day Load Forecast by Weather Zone
    #

    print("\nFetching NP3-561-CD…")
    load_fcst = client.get(
        "/np3-561-cd/7d_load_fcast_by_wzn",
        postedDatetimeFrom=iso_from, postedDatetimeTo=iso_to,
    )
    print(f"  {len(load_fcst)} rows")


    #
    # INSERT DB
    #

    print("\nWriting to Postgres…")
    with psycopg.connect(PG_DSN) as conn:
        n_outages = load_outages(conn, outages)
        n_dam_spp = load_dam_spp(conn, dam_spp)
        n_dam_shadow = load_dam_shadow_prices(conn, dam_shadow)
        n_dam_lambda = load_dam_lambda(conn, dam_lambda)
        n_sced_lambda = load_sced_lambda(conn, sced_lambda)
        n_load_fcst = load_load_forecast(conn, load_fcst)
        conn.commit()
        print(f"  outages_zonal:            {n_outages} inserted")
        print(f"  ercot_dam_spp:            {n_dam_spp} inserted")
        print(f"  ercot_dam_shadow_prices:  {n_dam_shadow} inserted")
        print(f"  dam_system_lambda:        {n_dam_lambda} inserted")
        print(f"  sced_system_lambda:       {n_sced_lambda} inserted")
        print(f"  load_forecast_zonal:      {n_load_fcst} inserted")

        print("\n--- Verification queries ---")
        print_recent_outages(conn, iso_from, iso_to)

if __name__ == "__main__":
    main()
