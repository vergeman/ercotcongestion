import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg
from psycopg.rows import dict_row


#
# LOADERS
#

# NB: records is a list comprehension of tuples passed to cursor
# loop through each dataframe row, process each column (_f)
# required columns use r[] (vs. r.get() )to trigger error
# executemany() batch inserts
#

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


def print_top_shadow_prices(conn, start_iso, end_iso, limit = 5) -> None:
    """Quick sanity check: top N binding constraints in a window."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT sced_timestamp, constraint_name, contingency_name, shadow_price
            FROM shadow_prices
            WHERE sced_timestamp BETWEEN %s AND %s
              AND shadow_price > 0
            ORDER BY shadow_price DESC
            LIMIT %s
            """,
            (start_iso, end_iso, limit),
        )
        print(f"\nTop {limit} binding constraints:")
        for row in cur.fetchall():
            print(
                f"  {row['sced_timestamp']}  "
                f"{row['constraint_name']:25s}  "
                f"{row['contingency_name']:15s}  "
                f"${row['shadow_price']:.2f}"
            )


def print_recent_outages(conn, start_iso, end_iso, limit = 5) -> None:
    """Quick sanity check: first N outage hours from latest publish in window."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT operating_date, hour_ending,
                   total_mw_south + total_mw_north + total_mw_west + total_mw_houston
                   AS total_outage_mw
            FROM outages_zonal
            WHERE posted_datetime BETWEEN %s AND %s
            ORDER BY posted_datetime DESC, operating_date, hour_ending
            LIMIT %s
            """,
            (start_iso, end_iso, limit),
        )
        print(f"\nFirst {limit} outage hours (latest publish):")
        for row in cur.fetchall():
            print(
                f"  {row['operating_date']} HE{row['hour_ending']:02d}  "
                f"{row['total_outage_mw']:.0f} MW total"
            )
