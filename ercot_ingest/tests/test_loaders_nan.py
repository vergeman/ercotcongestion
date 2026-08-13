"""Regression: NaN `gen_*` cells must never reach the DB as a non-null value.

Pins `loaders._f` end-to-end through `load_wind_hourly` (0129-0001). Postgres
stores NaN in a DOUBLE PRECISION column as a *non-null* value, so `IS NULL`
misses it, a sort over the series returns unsorted, and every percentile taken
from it is silently wrong -- which is what the brief's Context panel reads. The
loader routes every float through `_f`, which coerces NaN -> None, and psycopg
binds Python None as SQL NULL.

DB-free by design: it captures the exact tuples the loader hands to
`executemany` and asserts the NaN-fed cells became None (which psycopg persists
as SQL NULL) and that no NaN float survives anywhere in the batch. A future
refactor that drops the `_f` call fails loudly here instead of quietly poisoning
the panel.
"""
import math
import re

import pandas as pd

from loaders import load_wind_hourly


class _CapturingCursor:
    """Records the (sql, records) handed to executemany; no DB involved."""

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

    def __exit__(self, *a):
        return False


class _CapturingConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *a, **k):
        return self._cursor


def _insert_columns(sql: str) -> list[str]:
    """The INSERT column list, in order, so records can be read back by name
    rather than by a brittle positional index."""
    m = re.search(r"INSERT INTO wind_hourly_regional\s*\((.*?)\)", sql, re.S)
    assert m is not None, "could not locate the INSERT column list"
    return [c.strip() for c in m.group(1).split(",")]


def _api_row(delivery_date, hour_ending, posted, dst, value):
    """One NP4-742-CD API row. `value` fills every numeric field so a single
    input drives the whole record; pass float('nan') to exercise the guard."""
    row = {
        "deliveryDate": delivery_date,
        "hourEnding": hour_ending,
        "DSTFlag": dst,
        "postedDatetime": posted,
    }
    for region in ("SystemWide", "Panhandle", "Coastal", "South", "West", "North"):
        for metric in ("gen", "COPHSL", "STWPF", "WGRPP"):
            row[f"{metric}{region}"] = value
    row["HSLSystemWide"] = value
    return row


# Columns whose values come through `_f`; the guard must apply to all of them.
_NUMERIC_PREFIXES = ("gen_", "cop_hsl_", "stwpf_", "wgrpp_", "hsl_")


def test_nan_gen_persists_as_null():
    # Two rows on the same spring-forward day -- one all-NaN, one real -- so the
    # guard is checked both ways: it nulls NaN and leaves real values alone.
    df = pd.DataFrame([
        _api_row("2026-03-08", "01:00", "2026-03-08 06:00:00", False, float("nan")),
        _api_row("2026-03-08", "02:00", "2026-03-08 06:00:00", False, 123.5),
    ])

    cur = _CapturingCursor()
    load_wind_hourly(_CapturingConn(cur), df)
    assert cur.sql is not None and cur.records is not None, \
        "loader did not reach executemany"

    cols = _insert_columns(cur.sql)
    rows = [dict(zip(cols, rec)) for rec in cur.records]
    by_he = {r["hour_ending"]: r for r in rows}
    nan_row, clean_row = by_he[1], by_he[2]

    numeric_cols = [c for c in cols if c.startswith(_NUMERIC_PREFIXES)]
    assert numeric_cols, "no gen/forecast columns found in the INSERT"

    # The guard: every NaN-fed cell is None (-> SQL NULL), never a NaN float.
    for c in numeric_cols:
        assert nan_row[c] is None, f"{c} kept a non-null NaN instead of NULL"

    # ...and it does not clobber real values.
    for c in numeric_cols:
        assert clean_row[c] == 123.5, f"{c} lost its real value"

    # Belt-and-suspenders: no NaN float anywhere in the batch, any column.
    for r in rows:
        for v in r.values():
            assert not (isinstance(v, float) and math.isnan(v)), \
                "a NaN float reached the executemany batch"
