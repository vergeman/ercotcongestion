"""
Ingest 1 hour of NP6-86-CD + NP3-233-CD into Postgres.
Idempotent: re-running same window inserts zero new rows.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg
import requests
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

# --- ERCOT API ---
USERNAME = os.environ["ERCOT_USERNAME"]
PASSWORD = os.environ["ERCOT_PASSWORD"]
SUB_KEY = os.environ["ERCOT_SUBSCRIPTION_KEY"]
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
BASE_URL = "https://api.ercot.com/api/public-reports"

# --- Postgres ---
PG_DSN = (
    f"host={os.environ['PG_HOST']} port={os.environ['PG_PORT']} "
    f"dbname={os.environ['PG_DATABASE']} "
    f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}"
)


class ErcotClient:
    def __init__(self):
        self._token = None
        self._exp = 0

    def _get_token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        r = requests.post(
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
        r.raise_for_status()
        body = r.json()
        self._token = body["id_token"]
        self._exp = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def get(self, endpoint, **params):
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Ocp-Apim-Subscription-Key": SUB_KEY,
        }
        url = f"{BASE_URL}{endpoint}"
        rows, fields, page = [], None, 1
        while True:
            r = requests.get(
                url, headers=headers,
                params={**params, "page": page, "size": 1000},
                timeout=60,
            )
            if r.status_code >= 400:
                print(f"HTTP {r.status_code}: {r.text[:500]}")
                r.raise_for_status()
            p = r.json()
            if fields is None:
                fields = [f["name"] for f in p.get("fields", [])]
            rows.extend(p.get("data", []))
            meta = p.get("_meta", {})
            if page >= meta.get("totalPages", 1):
                break
            page += 1
        return pd.DataFrame(rows, columns=fields) if fields else pd.DataFrame()


# --- Loaders ---

def load_shadow_prices(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    records = [
        (
            r["SCEDTimestamp"], bool(r["repeatedHourFlag"]), int(r["constraintID"]),
            r["constraintName"], r["contingencyName"],
            _f(r["shadowPrice"]), _f(r["maxShadowPrice"]),
            _f(r["limit"]), _f(r["value"]), _f(r["violatedMW"]),
            r.get("fromStation"), r.get("toStation"),
            _f(r.get("fromStationkV")), _f(r.get("toStationkV")),
            r.get("CCTStatus"),
        )
        for _, r in df.iterrows()
    ]
    sql = """
        INSERT INTO shadow_prices (
            sced_timestamp, repeated_hour_flag, constraint_id, constraint_name,
            contingency_name, shadow_price, max_shadow_price, limit_mw, value_mw,
            violated_mw, from_station, to_station, from_kv, to_kv, cct_status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return cur.rowcount


def load_outages(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    records = [
        (
            r["postedDatetime"], r["operatingDate"], int(r["hourEnding"]),
            _f(r["totalResourceMWZoneSouth"]), _f(r["totalResourceMWZoneNorth"]),
            _f(r["totalResourceMWZoneWest"]), _f(r["totalResourceMWZoneHouston"]),
            _f(r["totalIRRMWZoneSouth"]), _f(r["totalIRRMWZoneNorth"]),
            _f(r["totalIRRMWZoneWest"]), _f(r["totalIRRMWZoneHouston"]),
            _f(r["totalNewEquipResourceMWZoneSouth"]), _f(r["totalNewEquipResourceMWZoneNorth"]),
            _f(r["totalNewEquipResourceMWZoneWest"]), _f(r["totalNewEquipResourceMWZoneHouston"]),
        )
        for _, r in df.iterrows()
    ]
    sql = """
        INSERT INTO outages_zonal (
            posted_datetime, operating_date, hour_ending,
            total_mw_south, total_mw_north, total_mw_west, total_mw_houston,
            irr_mw_south, irr_mw_north, irr_mw_west, irr_mw_houston,
            new_equip_mw_south, new_equip_mw_north, new_equip_mw_west, new_equip_mw_houston
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return cur.rowcount


def _f(x):
    """Coerce empty strings/None to None, else float."""
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# --- Main ---

def main():
    end = datetime.now(timezone.utc) - timedelta(days=2)
    end = end.replace(hour=22, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=1)
    iso_from = start.strftime("%Y-%m-%dT%H:%M:%S")
    iso_to = end.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"Window: {iso_from} → {iso_to}")

    client = ErcotClient()

    print("\nFetching NP6-86-CD…")
    shadow = client.get(
        "/np6-86-cd/shdw_prices_bnd_trns_const",
        SCEDTimestampFrom=iso_from, SCEDTimestampTo=iso_to,
    )
    print(f"  {len(shadow)} rows")

    print("Fetching NP3-233-CD…")
    outages = client.get(
        "/np3-233-cd/hourly_res_outage_cap",
        postedDatetimeFrom=iso_from, postedDatetimeTo=iso_to,
    )
    print(f"  {len(outages)} rows")

    print("\nWriting to Postgres…")
    with psycopg.connect(PG_DSN) as conn:
        n_shadow = load_shadow_prices(conn, shadow)
        n_outages = load_outages(conn, outages)
        conn.commit()
        print(f"  shadow_prices: {n_shadow} inserted")
        print(f"  outages_zonal: {n_outages} inserted")

        # Read back: top-5 highest shadow prices in window
        print("\n--- Verification queries ---")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT sced_timestamp, constraint_name, contingency_name, shadow_price
                FROM shadow_prices
                WHERE sced_timestamp BETWEEN %s AND %s
                  AND shadow_price > 0
                ORDER BY shadow_price DESC
                LIMIT 5
            """, (iso_from, iso_to))
            print("\nTop 5 binding constraints:")
            for row in cur.fetchall():
                print(f"  {row['sced_timestamp']}  {row['constraint_name']:25s}  "
                      f"{row['contingency_name']:15s}  ${row['shadow_price']:.2f}")

            cur.execute("""
                SELECT operating_date, hour_ending,
                       total_mw_south + total_mw_north + total_mw_west + total_mw_houston AS total_outage_mw
                FROM outages_zonal
                WHERE posted_datetime BETWEEN %s AND %s
                ORDER BY posted_datetime DESC, operating_date, hour_ending
                LIMIT 5
            """, (iso_from, iso_to))
            print("\nFirst 5 outage hours (latest publish):")
            for row in cur.fetchall():
                print(f"  {row['operating_date']} HE{row['hour_ending']:02d}  "
                      f"{row['total_outage_mw']:.0f} MW total")


if __name__ == "__main__":
    main()
