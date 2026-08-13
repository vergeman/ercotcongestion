"""NP4-158-SG loader contract, including ERCOT's Y/N DST flag."""
import re

import pandas as pd

from loaders import load_essp


class _CapturingCursor:
    def __init__(self):
        self.sql = None
        self.records = None
        self.rowcount = 0

    def executemany(self, sql, records):
        self.sql = sql
        self.records = list(records)
        self.rowcount = len(self.records)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _CapturingConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *args, **kwargs):
        return self._cursor


def _insert_columns(sql: str) -> list[str]:
    match = re.search(r"INSERT INTO ercot_essp\s*\((.*?)\)", sql, re.S)
    assert match is not None
    return [column.strip() for column in match.group(1).split(",")]


def test_load_essp_keeps_study_vintage_and_parses_ercot_timestamps():
    df = pd.DataFrame([
        {
            "DeliveryDate": "07/28/2026",
            "HourEnding": "01:00",
            "SettlementPoint": "BYP_RN",
            "GroupIndex": 17,
            "UpdateTime": "07/27/2026 05:55:00",
            "DSTFlag": "N",
        },
        {
            "DeliveryDate": "11/01/2026",
            "HourEnding": "02:00",
            "SettlementPoint": "HEN_RN",
            "GroupIndex": 17,
            "UpdateTime": "10/31/2026 05:55:00",
            "DSTFlag": "Y",
        },
    ])
    cur = _CapturingCursor()

    assert load_essp(_CapturingConn(cur), df, is_study=True) == 2

    assert cur.sql is not None and cur.records is not None
    assert "ON CONFLICT (interval_ts, settlement_point, is_study, dst_flag)" in cur.sql
    rows = [dict(zip(_insert_columns(cur.sql), record)) for record in cur.records]

    assert rows[0]["is_study"] is True
    assert rows[0]["dst_flag"] is False
    # HE01 begins at midnight CT (05:00Z in daylight time).
    assert rows[0]["interval_ts"].isoformat() == "2026-07-28T05:00:00+00:00"
    assert rows[0]["updated_at"].isoformat() == "2026-07-27T10:55:00+00:00"

    # The repeated fall-back HE02 begins at 01:00 standard time (07:00Z).
    assert rows[1]["dst_flag"] is True
    assert rows[1]["interval_ts"].isoformat() == "2026-11-01T07:00:00+00:00"
