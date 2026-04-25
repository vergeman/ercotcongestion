"""
ERCOT Public API smoke test (v2).
Pulls 1 hour of NP6-86-CD (SCED shadow prices) and NP3-233-CD (outages).
"""
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.environ["ERCOT_USERNAME"]
PASSWORD = os.environ["ERCOT_PASSWORD"]
SUB_KEY = os.environ["ERCOT_SUBSCRIPTION_KEY"]

CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
BASE_URL = "https://api.ercot.com/api/public-reports"


class ErcotClient:
    def __init__(self):
        self._token = None
        self._token_expires_at = 0

    def _get_token(self):
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "password",
                "username": USERNAME,
                "password": PASSWORD,
                "scope": f"openid {CLIENT_ID} offline_access",
                "client_id": CLIENT_ID,
                "response_type": "id_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["id_token"]
        self._token_expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def get(self, endpoint: str, **params) -> pd.DataFrame:
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Ocp-Apim-Subscription-Key": SUB_KEY,
        }
        url = f"{BASE_URL}{endpoint}"
        all_rows = []
        fields = None
        page = 1
        while True:
            r = requests.get(
                url,
                headers=headers,
                params={**params, "page": page, "size": 1000},
                timeout=60,
            )
            if r.status_code >= 400:
                print(f"\nHTTP {r.status_code} for {r.url}")
                print(f"Body: {r.text[:1000]}")
                r.raise_for_status()
            payload = r.json()
            if fields is None:
                fields = [f["name"] for f in payload.get("fields", [])]
            # ERCOT returns rows as list-of-lists, parallel to fields
            rows = payload.get("data", [])
            all_rows.extend(rows)
            meta = payload.get("_meta", {})
            total_pages = meta.get("totalPages", 1)
            if page >= total_pages or not rows:
                break
            page += 1
        if not fields:
            return pd.DataFrame()
        return pd.DataFrame(all_rows, columns=fields)


def main():
    client = ErcotClient()

    # Two days ago at ~5pm CT (22:00 UTC) — peak hour, data fully posted
    end = datetime.utcnow() - timedelta(days=2)
    end = end.replace(hour=22, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=1)

    iso_from = start.strftime("%Y-%m-%dT%H:%M:%S")
    iso_to = end.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"Window: {iso_from} → {iso_to} (UTC)\n")

    print("=" * 60)
    print("NP6-86-CD: SCED shadow prices")
    print("=" * 60)
    shadow = client.get(
        "/np6-86-cd/shdw_prices_bnd_trns_const",
        SCEDTimestampFrom=iso_from,
        SCEDTimestampTo=iso_to,
    )
    print(f"Rows: {len(shadow)}")
    if len(shadow):
        print(shadow.head(10).to_string())
        print(f"\nColumns: {list(shadow.columns)}")
    else:
        print("(No binding constraints in this window — try a different hour)")

    print("\n" + "=" * 60)
    print("NP3-233-CD: Hourly resource outage capacity")
    print("=" * 60)
    outages = client.get(
        "/np3-233-cd/hourly_res_outage_cap",
        postedDatetimeFrom=iso_from,
        postedDatetimeTo=iso_to,
    )
    print(f"Rows: {len(outages)}")
    if len(outages):
        print(outages.head(10).to_string())
        print(f"\nColumns: {list(outages.columns)}")


if __name__ == "__main__":
    main()
