"""Focused contract tests for shared forecast persistence."""
from __future__ import annotations

import pandas as pd

from compute import forecast_store
from compute.time import ct_day_bounds


class _Copy:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def write_row(self, row):
        self.events.append(("copy-row", row))


class _Cursor:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.events.append(("execute", sql, params))

    def copy(self, sql):
        self.events.append(("copy", sql))
        return _Copy(self.events)


class _Connection:
    def __init__(self):
        self.events = []

    def cursor(self):
        return _Cursor(self.events)


def test_nodal_store_scopes_ct_day_horizon_and_copy_rows(monkeypatch):
    day = pd.Timestamp("2026-07-30").date()
    frame = pd.DataFrame({
        "ts": pd.DatetimeIndex([
            "2026-07-30 05:00:00+00:00",  # 07-30 00:00 CT
            "2026-07-31 04:00:00+00:00",  # 07-30 23:00 CT
            "2026-07-31 05:00:00+00:00",  # 07-31 00:00 CT
        ]),
        "settlement_point": ["A", "B", "C"],
        "point": [2.5, float("nan"), 4.5],
    })
    monkeypatch.setattr(forecast_store, "load_nodal", lambda _: frame)
    conn = _Connection()

    assert forecast_store.nodal_to_db("panel.npz", conn, run_id="run",
                                      delivery_date=day, horizon=2) == 2

    delete = conn.events[0]
    lo, hi = ct_day_bounds(day)
    assert delete[0] == "execute"
    assert delete[2] == ("run", 2, lo, hi)
    rows = [event[1] for event in conn.events if event[0] == "copy-row"]
    assert [row[1] for row in rows] == ["2026-07-30", "2026-07-30"]
    assert [row[-1] for row in rows] == [2, 2]
    assert rows[1][4] is None


def test_store_writes_artifact_before_the_pointer():
    conn = _Connection()

    forecast_store.sf_artifact_to_db(conn, run_id="run", delivery_date="2026-07-30",
                                     sf_npz=b"artifact", horizon=1)
    forecast_store.upsert_pointer(conn, "test", "run")

    statements = [event[1] for event in conn.events if event[0] == "execute"]
    assert "forecast_sf_artifact" in statements[0]
    assert "forecast_current" in statements[1]
