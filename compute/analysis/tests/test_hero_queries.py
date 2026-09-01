from datetime import date

from compute.analysis.hero_queries import (
    daily_total,
    load_constraint_days,
    load_constraint_geo,
    load_forecast_constraint_days,
    load_load_condition,
    summarize_load_condition,
)
from compute.time import delivery_bounds


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = self.params = None

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Conn:
    def __init__(self, rows):
        self.cur = Cursor(rows)

    def cursor(self):
        return self.cur


def test_delivery_bounds_use_central_time_including_summer_offset():
    start, end = delivery_bounds(date(2026, 7, 28))
    assert start.isoformat() == "2026-07-28T05:00:00+00:00"
    assert end.isoformat() == "2026-07-29T05:00:00+00:00"


def test_constraint_window_aggregates_in_sql_and_has_a_strict_as_of_end_bound():
    conn = Conn([(date(2026, 7, 28), "A|B", 12.5, 3)])
    rows = load_constraint_days(conn, date(2026, 7, 28), constraint_keys=["A|B"])
    assert rows[0]["value"] == 12.5
    assert "GROUP BY 1, 2" in conn.cur.sql
    assert "interval_ts < %s" in conn.cur.sql
    assert "btrim(constraint_name) || '|' || btrim(contingency_name)" in conn.cur.sql
    assert "ANY(%s)" in conn.cur.sql
    assert conn.cur.params[-1] == ["A|B"]

    load_constraint_days(conn, date(2026, 7, 28), ct_hours=(15, 16, 17, 18))
    assert "EXTRACT(hour FROM interval_ts AT TIME ZONE 'America/Chicago') = ANY(%s)" in conn.cur.sql
    assert conn.cur.params[-1] == [15, 16, 17, 18]


def test_forecast_constraint_window_uses_the_persisted_artifact_history_vocabulary():
    conn = Conn([(date(2026, 7, 28), "A|B", 12.5, 3)])
    rows = load_forecast_constraint_days(conn, "mu-v1", date(2026, 7, 28), 1,
                                         constraint_keys=["A|B"])
    assert rows == [{"delivery_date": date(2026, 7, 28), "constraint_key": "A|B",
                     "value": 12.5, "binding_hours": 3}]
    assert "FROM forecast_constraint_daily" in conn.cur.sql
    assert "constraint_key = ANY(%s)" in conn.cur.sql
    assert conn.cur.params == ("mu-v1", 1, date(2026, 6, 28), date(2026, 7, 28), ["A|B"])


def test_daily_total_zero_fills_missing_days():
    assert daily_total([
        {"delivery_date": date(2026, 7, 27), "constraint_key": "A|B", "value": 9},
    ], date(2026, 7, 28), days=2) == [0.0, 9.0, 0.0]


def test_load_window_uses_a_strict_cutoff_rule():
    load_conn = Conn([])
    load_load_condition(load_conn, date(2026, 7, 28))
    assert "interval_ts < %s" in load_conn.cur.sql
    assert "posted_datetime <=" in load_conn.cur.sql
    assert "FROM wind_forecast_regional" in load_conn.cur.sql
    assert "FROM solar_forecast_regional" in load_conn.cur.sql
    assert "FROM load_by_zone" in load_conn.cur.sql
    assert "JOIN wind_hourly_regional" in load_conn.cur.sql
    assert "JOIN solar_hourly_regional" in load_conn.cur.sql
    assert "l.dst_flag = FALSE" not in load_conn.cur.sql

    geo_conn = Conn([])
    load_constraint_geo(geo_conn)
    assert "window_start = (SELECT max(window_start) FROM constraint_geo)" in geo_conn.cur.sql


def test_condition_summary_carries_classifier_ready_percentiles():
    condition = summarize_load_condition([
        {"delivery_date": date(2026, 7, 26), "value": 80,
         "actual_value": 78, "actual_net_load": 60},
        {"delivery_date": date(2026, 7, 27), "value": 90,
         "actual_value": 88, "actual_net_load": 68},
        {"delivery_date": date(2026, 7, 28), "value": 100, "net_load": 70,
         "actual_value": 98, "actual_net_load": 75},
    ])
    assert condition == {"series": "load.system", "today": 100.0, "net_load": 70.0,
                         "actual_today": 98.0, "actual_net_load": 75.0, "median": 90.0,
                         "pct": 100.0, "wind_peak": None, "solar_peak": None,
                         "wind_pct": None, "solar_pct": None, "load_miss_pct": -2.0,
                         "load_miss_abs": 2.0, "n": 3, "basis": "forecast"}
