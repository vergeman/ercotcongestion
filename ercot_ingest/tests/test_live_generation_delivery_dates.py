"""Regression coverage for the live wind/solar Central delivery-date filter."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from backfill import backfill_one_window, central_delivery_date_window


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # CDT: UTC midnight is 19:00 locally; do not jump to the next delivery day.
        ("2026-08-21T00:00:00+00:00", "2026-08-21T02:00:00+00:00",
         ("2026-08-20", "2026-08-20")),
        # CST: UTC midnight is 18:00 locally.
        ("2026-01-16T00:00:00+00:00", "2026-01-16T02:00:00+00:00",
         ("2026-01-15", "2026-01-15")),
        # A window ending exactly at local midnight must not include tomorrow.
        ("2026-08-21T04:00:00+00:00", "2026-08-21T05:00:00+00:00",
         ("2026-08-20", "2026-08-20")),
        # A normal daytime window remains on its local delivery date.
        ("2026-08-21T17:00:00+00:00", "2026-08-21T19:00:00+00:00",
         ("2026-08-21", "2026-08-21")),
    ],
)
def test_central_delivery_date_window(start, end, expected):
    got = central_delivery_date_window(datetime.fromisoformat(start), datetime.fromisoformat(end))
    assert tuple(day.isoformat() for day in got) == expected


class _Cursor:
    def execute(self, *_args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Conn:
    def cursor(self):
        return _Cursor()

    def commit(self):
        pass


class _Client:
    def __init__(self):
        self.params = None

    def get(self, _path, **params):
        self.params = params
        return pd.DataFrame()


def test_live_generation_request_uses_explicit_central_delivery_dates():
    client = _Client()
    start = datetime(2026, 8, 21, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 21, 2, tzinfo=timezone.utc)

    backfill_one_window(
        client, _Conn(), "wind", start, end, resume=False,
        delivery_date_window=central_delivery_date_window(start, end),
    )

    assert client.params["deliveryDateFrom"] == "2026-08-20"
    assert client.params["deliveryDateTo"] == "2026-08-20"
