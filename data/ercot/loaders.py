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


def load_load_by_zone(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    #print(f"  load_by_zone columns: {df.columns.tolist()}")
    #print(f"  first row: {df.iloc[0].to_dict()}")

    records = []

    for _, r in df.iterrows():
        op_day = pd.to_datetime(r["operatingDay"]).date()

        # hourEnding comes as "01:00", "02:00", ... "24:00"
        he_raw = r["hourEnding"]
        if isinstance(he_raw, str) and ":" in he_raw:
            hour = int(he_raw.split(":")[0])
        else:
            hour = int(he_raw)

        # NP6-345-CD is hourly (not 15-min) — interval is always 1
        interval = 1
        dst = bool(r.get("dstFlag", False))
        ts = _to_interval_ts(op_day, hour, interval, dst)

        records.append((
            op_day, hour, interval,
            _f(r.get("coast")), _f(r.get("east")), _f(r.get("farWest")),
            _f(r.get("north")), _f(r.get("northC")), _f(r.get("southC")),
            _f(r.get("southern")), _f(r.get("west")), _f(r.get("total")),
            dst, ts,
        ))

    sql = """
        INSERT INTO load_by_zone (
            operating_day, hour_ending, interval_id,
            coast, east, far_west, north, north_central, south_central,
            southern, west, total, dst_flag, interval_ts
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return cur.rowcount


def load_wind_hourly(conn, df: pd.DataFrame) -> int:
    """Load NP4-742-CD: Wind Power Production by Geographical Region.

    5 wind regions: Panhandle, Coastal, South, West, North.
    Replaces the old NP4-732-CD system-wide + 3-zone subset loader.
    """
    if df.empty:
        return 0

    # Dedup: keep most recent posting per (delivery_date, hour_ending, dst_flag)
    df = df.sort_values("postedDatetime").drop_duplicates(
        subset=["deliveryDate", "hourEnding", "DSTFlag"],
        keep="last",
    )

    records = []
    for _, r in df.iterrows():
        op_day = pd.to_datetime(r["deliveryDate"]).date()
        he_raw = r["hourEnding"]
        hour = int(he_raw.split(":")[0]) if isinstance(he_raw, str) else int(he_raw)
        dst = bool(r.get("DSTFlag", False))
        ts = _to_interval_ts(op_day, hour, 1, dst)

        records.append((
            op_day, hour, pd.to_datetime(r["postedDatetime"]), dst, ts,
            # System-wide
            _f(r.get("genSystemWide")), _f(r.get("COPHSLSystemWide")),
            _f(r.get("STWPFSystemWide")), _f(r.get("WGRPPSystemWide")),
            _f(r.get("HSLSystemWide")),
            # Panhandle
            _f(r.get("genPanhandle")), _f(r.get("COPHSLPanhandle")),
            _f(r.get("STWPFPanhandle")), _f(r.get("WGRPPPanhandle")),
            # Coastal
            _f(r.get("genCoastal")), _f(r.get("COPHSLCoastal")),
            _f(r.get("STWPFCoastal")), _f(r.get("WGRPPCoastal")),
            # South
            _f(r.get("genSouth")), _f(r.get("COPHSLSouth")),
            _f(r.get("STWPFSouth")), _f(r.get("WGRPPSouth")),
            # West
            _f(r.get("genWest")), _f(r.get("COPHSLWest")),
            _f(r.get("STWPFWest")), _f(r.get("WGRPPWest")),
            # North
            _f(r.get("genNorth")), _f(r.get("COPHSLNorth")),
            _f(r.get("STWPFNorth")), _f(r.get("WGRPPNorth")),
        ))

    sql = """
        INSERT INTO wind_hourly_regional (
            delivery_date, hour_ending, posted_datetime, dst_flag, interval_ts,
            gen_system_wide, cop_hsl_system_wide, stwpf_system_wide,
            wgrpp_system_wide, hsl_system_wide,
            gen_panhandle, cop_hsl_panhandle, stwpf_panhandle, wgrpp_panhandle,
            gen_coastal,   cop_hsl_coastal,   stwpf_coastal,   wgrpp_coastal,
            gen_south,     cop_hsl_south,     stwpf_south,     wgrpp_south,
            gen_west,      cop_hsl_west,      stwpf_west,      wgrpp_west,
            gen_north,     cop_hsl_north,     stwpf_north,     wgrpp_north
        ) VALUES (
            %s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s
        )
        ON CONFLICT (interval_ts, dst_flag) DO UPDATE SET
            posted_datetime     = EXCLUDED.posted_datetime,
            gen_system_wide     = EXCLUDED.gen_system_wide,
            cop_hsl_system_wide = EXCLUDED.cop_hsl_system_wide,
            stwpf_system_wide   = EXCLUDED.stwpf_system_wide,
            wgrpp_system_wide   = EXCLUDED.wgrpp_system_wide,
            hsl_system_wide     = EXCLUDED.hsl_system_wide,
            gen_panhandle       = EXCLUDED.gen_panhandle,
            cop_hsl_panhandle   = EXCLUDED.cop_hsl_panhandle,
            stwpf_panhandle     = EXCLUDED.stwpf_panhandle,
            wgrpp_panhandle     = EXCLUDED.wgrpp_panhandle,
            gen_coastal         = EXCLUDED.gen_coastal,
            cop_hsl_coastal     = EXCLUDED.cop_hsl_coastal,
            stwpf_coastal       = EXCLUDED.stwpf_coastal,
            wgrpp_coastal       = EXCLUDED.wgrpp_coastal,
            gen_south           = EXCLUDED.gen_south,
            cop_hsl_south       = EXCLUDED.cop_hsl_south,
            stwpf_south         = EXCLUDED.stwpf_south,
            wgrpp_south         = EXCLUDED.wgrpp_south,
            gen_west            = EXCLUDED.gen_west,
            cop_hsl_west        = EXCLUDED.cop_hsl_west,
            stwpf_west          = EXCLUDED.stwpf_west,
            wgrpp_west          = EXCLUDED.wgrpp_west,
            gen_north           = EXCLUDED.gen_north,
            cop_hsl_north       = EXCLUDED.cop_hsl_north,
            stwpf_north         = EXCLUDED.stwpf_north,
            wgrpp_north         = EXCLUDED.wgrpp_north
        WHERE wind_hourly_regional.posted_datetime < EXCLUDED.posted_datetime
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return cur.rowcount


def load_solar_hourly(conn, df: pd.DataFrame) -> int:
    """Load NP4-745-CD: Solar Power Production by Geographical Region.

    6 PV regions: CenterWest, NorthWest, FarWest, FarEast, SouthEast, CenterEast.
    Replaces the old NP4-737-CD system-wide-only loader.
    """
    if df.empty:
        return 0

    df = df.sort_values("postedDatetime").drop_duplicates(
        subset=["deliveryDate", "hourEnding", "DSTFlag"],
        keep="last",
    )

    records = []
    for _, r in df.iterrows():
        op_day = pd.to_datetime(r["deliveryDate"]).date()
        he_raw = r["hourEnding"]
        hour = int(he_raw.split(":")[0]) if isinstance(he_raw, str) else int(he_raw)
        dst = bool(r.get("DSTFlag", False))
        ts = _to_interval_ts(op_day, hour, 1, dst)

        records.append((
            op_day, hour, pd.to_datetime(r["postedDatetime"]), dst, ts,
            # System-wide
            _f(r.get("genSystemWide")), _f(r.get("COPHSLSystemWide")),
            _f(r.get("STPPFSystemWide")), _f(r.get("PVGRPPSystemWide")),
            _f(r.get("HSLSystemWide")),
            # CenterWest
            _f(r.get("genCenterWest")), _f(r.get("COPHSLCenterWest")),
            _f(r.get("STPPFCenterWest")), _f(r.get("PVGRPPCenterWest")),
            # NorthWest
            _f(r.get("genNorthWest")), _f(r.get("COPHSLNorthWest")),
            _f(r.get("STPPFNorthWest")), _f(r.get("PVGRPPNorthWest")),
            # FarWest
            _f(r.get("genFarWest")), _f(r.get("COPHSLFarWest")),
            _f(r.get("STPPFFarWest")), _f(r.get("PVGRPPFarWest")),
            # FarEast
            _f(r.get("genFarEast")), _f(r.get("COPHSLFarEast")),
            _f(r.get("STPPFFarEast")), _f(r.get("PVGRPPFarEast")),
            # SouthEast
            _f(r.get("genSouthEast")), _f(r.get("COPHSLSouthEast")),
            _f(r.get("STPPFSouthEast")), _f(r.get("PVGRPPSouthEast")),
            # CenterEast
            _f(r.get("genCenterEast")), _f(r.get("COPHSLCenterEast")),
            _f(r.get("STPPFCenterEast")), _f(r.get("PVGRPPCenterEast")),
        ))

    sql = """
        INSERT INTO solar_hourly_regional (
            delivery_date, hour_ending, posted_datetime, dst_flag, interval_ts,
            gen_system_wide, cop_hsl_system_wide, stppf_system_wide,
            pvgrpp_system_wide, hsl_system_wide,
            gen_centerwest, cop_hsl_centerwest, stppf_centerwest, pvgrpp_centerwest,
            gen_northwest,  cop_hsl_northwest,  stppf_northwest,  pvgrpp_northwest,
            gen_farwest,    cop_hsl_farwest,    stppf_farwest,    pvgrpp_farwest,
            gen_fareast,    cop_hsl_fareast,    stppf_fareast,    pvgrpp_fareast,
            gen_southeast,  cop_hsl_southeast,  stppf_southeast,  pvgrpp_southeast,
            gen_centereast, cop_hsl_centereast, stppf_centereast, pvgrpp_centereast
        ) VALUES (
            %s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,%s,%s
        )
        ON CONFLICT (interval_ts, dst_flag) DO UPDATE SET
            posted_datetime     = EXCLUDED.posted_datetime,
            gen_system_wide     = EXCLUDED.gen_system_wide,
            cop_hsl_system_wide = EXCLUDED.cop_hsl_system_wide,
            stppf_system_wide   = EXCLUDED.stppf_system_wide,
            pvgrpp_system_wide  = EXCLUDED.pvgrpp_system_wide,
            hsl_system_wide     = EXCLUDED.hsl_system_wide,
            gen_centerwest      = EXCLUDED.gen_centerwest,
            cop_hsl_centerwest  = EXCLUDED.cop_hsl_centerwest,
            stppf_centerwest    = EXCLUDED.stppf_centerwest,
            pvgrpp_centerwest   = EXCLUDED.pvgrpp_centerwest,
            gen_northwest       = EXCLUDED.gen_northwest,
            cop_hsl_northwest   = EXCLUDED.cop_hsl_northwest,
            stppf_northwest     = EXCLUDED.stppf_northwest,
            pvgrpp_northwest    = EXCLUDED.pvgrpp_northwest,
            gen_farwest         = EXCLUDED.gen_farwest,
            cop_hsl_farwest     = EXCLUDED.cop_hsl_farwest,
            stppf_farwest       = EXCLUDED.stppf_farwest,
            pvgrpp_farwest      = EXCLUDED.pvgrpp_farwest,
            gen_fareast         = EXCLUDED.gen_fareast,
            cop_hsl_fareast     = EXCLUDED.cop_hsl_fareast,
            stppf_fareast       = EXCLUDED.stppf_fareast,
            pvgrpp_fareast      = EXCLUDED.pvgrpp_fareast,
            gen_southeast       = EXCLUDED.gen_southeast,
            cop_hsl_southeast   = EXCLUDED.cop_hsl_southeast,
            stppf_southeast     = EXCLUDED.stppf_southeast,
            pvgrpp_southeast    = EXCLUDED.pvgrpp_southeast,
            gen_centereast      = EXCLUDED.gen_centereast,
            cop_hsl_centereast  = EXCLUDED.cop_hsl_centereast,
            stppf_centereast    = EXCLUDED.stppf_centereast,
            pvgrpp_centereast   = EXCLUDED.pvgrpp_centereast
        WHERE solar_hourly_regional.posted_datetime < EXCLUDED.posted_datetime
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return cur.rowcount


def _to_interval_ts(operating_day, hour_ending: int, interval_id: int = 1, dst_flag: bool = False):
    """
    ERCOT publishes hour_ending in CT. Convert to UTC.
    interval_id is 1-4 for 15-min slices (load), or always 1 for hourly reports.
    """
    from zoneinfo import ZoneInfo
    ct = ZoneInfo("America/Chicago")
    # hour_ending=1 means the interval ending at 01:00 CT, i.e. 00:15-01:00 for 15-min
    # For hourly: the interval is the full hour ending at hour_ending CT
    minute = (interval_id - 1) * 15 if interval_id else 0
    naive = datetime(operating_day.year, operating_day.month, operating_day.day,
                     hour_ending - 1, minute)
    # dst_flag=True is the second occurrence (fall back)
    aware = naive.replace(tzinfo=ct, fold=1 if dst_flag else 0)
    return aware.astimezone(timezone.utc)


def _f(x):
    """Coerce empty strings/None to None, else float."""
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

#
# PRINT
#

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
