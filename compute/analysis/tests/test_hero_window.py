from datetime import date

from compute.analysis.hero_window import (
    delivery_bounds,
    daily_total,
    load_constraint_days,
    load_constraint_geo,
    load_load_condition,
    load_node_days,
    summarize_constraint_days,
    summarize_load_condition,
    summarize_node_days,
)


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


def test_constraint_summary_carries_series_median_and_previous_day():
    summary = summarize_constraint_days([
        {"delivery_date": date(2026, 7, 26), "constraint_key": "A|B", "value": 3, "hours_bound": 1},
        {"delivery_date": date(2026, 7, 27), "constraint_key": "A|B", "value": 9, "hours_bound": 2},
        {"delivery_date": date(2026, 7, 28), "constraint_key": "A|B", "value": 6, "hours_bound": 1},
    ])
    assert summary["A|B"]["days_bound"] == 3
    assert summary["A|B"]["med"] == 6
    assert summary["A|B"]["prior_last"] == 9
    assert daily_total([
        {"delivery_date": date(2026, 7, 27), "constraint_key": "A|B", "value": 9},
    ], date(2026, 7, 28), days=2) == [0.0, 9.0, 0.0]


def test_node_and_load_windows_use_the_same_strict_cutoff_rule():
    node_conn = Conn([])
    load_node_days(node_conn, date(2026, 7, 28))
    assert "AVG(s.dam_spp - l.system_lambda)" in node_conn.cur.sql
    assert "s.interval_ts < %s" in node_conn.cur.sql

    load_conn = Conn([])
    load_load_condition(load_conn, date(2026, 7, 28))
    assert "interval_ts < %s" in load_conn.cur.sql
    assert "posted_datetime <=" in load_conn.cur.sql

    geo_conn = Conn([])
    load_constraint_geo(geo_conn)
    assert "window_start = (SELECT max(window_start) FROM constraint_geo)" in geo_conn.cur.sql


def test_node_and_condition_summaries_carry_classifier_ready_ranks_and_percentiles():
    nodes = summarize_node_days([
        {"delivery_date": date(2026, 7, 27), "settlement_point": "A", "value": -5},
        {"delivery_date": date(2026, 7, 28), "settlement_point": "A", "value": 3},
    ])
    assert nodes["A"]["rank"] == 2 and nodes["A"]["n"] == 2

    condition = summarize_load_condition([
        {"delivery_date": date(2026, 7, 26), "value": 80},
        {"delivery_date": date(2026, 7, 27), "value": 90},
        {"delivery_date": date(2026, 7, 28), "value": 100},
    ])
    assert condition == {"series": "load.system", "today": 100.0, "median": 90.0,
                         "pct": 100.0, "n": 3, "basis": "forecast"}
