"""Database-backed source readers for the μ feature panel."""
from __future__ import annotations

import pandas as pd

from compute.mu.availability import ERCOT_TZ, vintage_cutoff_expr


def _read(conn, sql: str, params, index_col: str | None = None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [description[0] for description in cur.description]
        frame = pd.DataFrame(cur.fetchall(), columns=columns)
    return frame.set_index(index_col) if index_col else frame


def load_forecast_panel(conn, start, end, vintage_cutoff=None) -> pd.DataFrame:
    cutoff, params = vintage_cutoff_expr("interval_ts", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (interval_ts) interval_ts, posted_datetime,
               coast, east, far_west, north, north_central, south_central,
               southern, west, system_total
          FROM load_forecast_zonal
         WHERE interval_ts >= %s AND interval_ts < %s AND posted_datetime <= {cutoff}
         ORDER BY interval_ts, posted_datetime DESC
    """
    frame = _read(conn, sql, (start, end) + params, index_col="interval_ts")
    return frame.add_prefix("load_").rename(columns={"load_posted_datetime": "vintage_load"})


def wind_forecast_panel(conn, start, end, vintage_cutoff=None) -> pd.DataFrame:
    cutoff, params = vintage_cutoff_expr("interval_ts", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (interval_ts) interval_ts, posted_datetime,
               stwpf_system_wide, stwpf_panhandle, stwpf_coastal, stwpf_south,
               stwpf_west, stwpf_north, wgrpp_system_wide
          FROM wind_forecast_regional
         WHERE interval_ts >= %s AND interval_ts < %s AND posted_datetime <= {cutoff}
         ORDER BY interval_ts, posted_datetime DESC
    """
    frame = _read(conn, sql, (start, end) + params, index_col="interval_ts")
    return frame.rename(columns={"posted_datetime": "vintage_wind"})


def solar_forecast_panel(conn, start, end, vintage_cutoff=None) -> pd.DataFrame:
    cutoff, params = vintage_cutoff_expr("interval_ts", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (interval_ts) interval_ts, posted_datetime,
               stppf_system_wide, stppf_centerwest, stppf_northwest, stppf_farwest,
               stppf_fareast, stppf_southeast, stppf_centereast, pvgrpp_system_wide
          FROM solar_forecast_regional
         WHERE interval_ts >= %s AND interval_ts < %s AND posted_datetime <= {cutoff}
         ORDER BY interval_ts, posted_datetime DESC
    """
    frame = _read(conn, sql, (start, end) + params, index_col="interval_ts")
    return frame.rename(columns={"posted_datetime": "vintage_solar"})


def outage_panel(conn, start, end, vintage_cutoff=None) -> pd.DataFrame:
    cutoff, params = vintage_cutoff_expr(
        "(operating_date::timestamp AT TIME ZONE '" + ERCOT_TZ + "')", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (operating_date, hour_ending)
               operating_date, hour_ending, posted_datetime, total_mw_south,
               total_mw_north, total_mw_west, total_mw_houston, irr_mw_south,
               irr_mw_north, irr_mw_west, irr_mw_houston
          FROM outages_zonal
         WHERE operating_date >= %s AND operating_date < %s AND posted_datetime <= {cutoff}
         ORDER BY operating_date, hour_ending, posted_datetime DESC
    """
    frame = _read(conn, sql, (pd.Timestamp(start).date(), pd.Timestamp(end).date()) + params)
    if frame.empty:
        return pd.DataFrame()
    local = (pd.to_datetime(frame["operating_date"])
             + pd.to_timedelta(frame["hour_ending"].astype(int) - 1, unit="h"))
    frame["interval_ts"] = (local.dt.tz_localize(ERCOT_TZ, ambiguous=True,
                                                  nonexistent="shift_forward")
                            .dt.tz_convert("UTC"))
    frame = frame.drop(columns=["operating_date", "hour_ending"]).set_index("interval_ts")
    return frame[~frame.index.duplicated(keep="last")].rename(
        columns={"posted_datetime": "vintage_outage"})
