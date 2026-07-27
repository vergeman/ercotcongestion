"""Day-keyed live refresh for `dam_spp` (plan 0122 item 5).

What's pinned is the decision — which days get asked for, and whether an
already-ingested day costs a fetch — so the client is a recorder and the loader a
no-op. `ingest_log` is real: sharing its key with the CLI backfill is the throttle.

Runs in the compute container (needs Postgres + `ercot_ingest` on the path).
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ercot_ingest"))

backfill = pytest.importorskip(
    "backfill", reason="ercot_ingest imports need the compute container's env")

ERCOT_TZ = backfill.ERCOT_TZ


class _RecordingClient:
    """Records the date labels each call asked for."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def get(self, path, **params):
        self.calls.append((params["deliveryDateFrom"], params["deliveryDateTo"]))
        return pd.DataFrame()          # 0 rows — the loader is stubbed anyway


@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        dsn = (f"host={os.environ['PG_HOST']} "
               f"dbname={os.environ.get('PG_DB', 'ercot')} "
               f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    except KeyError:
        pytest.skip("no PG_* env — DB tests run in the compute container only")
    try:
        c = psycopg.connect(dsn, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres unreachable: {e}")
    with c:
        yield c


@pytest.fixture
def endpoint(conn, monkeypatch):
    """A scratch key wearing `dam_spp`'s config, so the test never touches the real
    feed's throttle state."""
    key = f"zz-test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setitem(backfill.ENDPOINTS, key,
                        {**backfill.ENDPOINTS["dam_spp"], "loader": lambda c, df: 0})
    try:
        yield key
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ingest_log WHERE endpoint = %s", (key,))
        conn.commit()


def _run_at(client, conn, endpoint, ct_wall: str, monkeypatch):
    """Run one cycle as if the wall clock in CT were `ct_wall`."""
    fake_now = pd.Timestamp(ct_wall, tz="America/Chicago").tz_convert("UTC")

    class _dt(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now.to_pydatetime()

    monkeypatch.setattr(backfill, "datetime", _dt)
    backfill.update_recent_daily(client, conn, keys=(endpoint,))


def _mark_done(conn, endpoint, day: date, rows: int = 26736):
    """Log `day` complete, as the CLI backfill would."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    backfill.log_completion(conn, endpoint, start, start + timedelta(days=1),
                            rows, rows)
    conn.commit()


def test_days_already_in_the_log_cost_no_fetch(conn, endpoint, monkeypatch):
    """The throttle itself: every target day complete → zero API calls."""
    now = "2026-07-26 15:00"
    today = date(2026, 7, 26)
    for offset in range(-backfill.LIVE_LOOKBACK_DAYS, 2):   # lookback .. tomorrow
        _mark_done(conn, endpoint, today + timedelta(days=offset))

    client = _RecordingClient()
    _run_at(client, conn, endpoint, now, monkeypatch)
    assert client.calls == []


def test_tomorrows_dam_is_requested_by_name_once_published(conn, endpoint,
                                                           monkeypatch):
    """Tomorrow is asked for after 14:00 CT and not before."""
    for offset in range(-backfill.LIVE_LOOKBACK_DAYS, 1):
        _mark_done(conn, endpoint, date(2026, 7, 26) + timedelta(days=offset))

    early = _RecordingClient()
    _run_at(early, conn, endpoint, "2026-07-26 09:00", monkeypatch)
    assert early.calls == []                       # before publication: not asked

    late = _RecordingClient()
    _run_at(late, conn, endpoint, "2026-07-26 15:00", monkeypatch)
    assert late.calls == [("2026-07-27", "2026-07-27")]


def test_whole_day_labels_are_preserved(conn, endpoint, monkeypatch):
    """One complete delivery day per fetch. Narrowing the label is what would make
    tomorrow's DAM unreachable."""
    client = _RecordingClient()
    _run_at(client, conn, endpoint, "2026-07-26 15:00", monkeypatch)
    assert client.calls == [(d, d) for d in ("2026-07-23", "2026-07-24",
                                             "2026-07-25", "2026-07-26",
                                             "2026-07-27")]


def test_a_missing_day_is_refetched_while_its_neighbours_are_not(conn, endpoint,
                                                                 monkeypatch):
    """The lookback is a repair window, not recurring work: only the gap is fetched."""
    today = date(2026, 7, 26)
    for offset in range(-backfill.LIVE_LOOKBACK_DAYS, 2):
        if offset != -2:
            _mark_done(conn, endpoint, today + timedelta(days=offset))

    client = _RecordingClient()
    _run_at(client, conn, endpoint, "2026-07-26 15:00", monkeypatch)
    assert client.calls == [("2026-07-24", "2026-07-24")]


def test_an_empty_fetch_is_retried_next_cycle(conn, endpoint, monkeypatch):
    """Logged-but-empty means not published yet, not done: `is_completed` requires
    rows_fetched > 0, so a day asked for a minute too early still gets filled."""
    today = date(2026, 7, 26)
    for offset in range(-backfill.LIVE_LOOKBACK_DAYS, 1):
        _mark_done(conn, endpoint, today + timedelta(days=offset))
    _mark_done(conn, endpoint, today + timedelta(days=1), rows=0)

    client = _RecordingClient()
    _run_at(client, conn, endpoint, "2026-07-26 15:00", monkeypatch)
    assert client.calls == [("2026-07-27", "2026-07-27")]


def test_dam_spp_is_the_only_endpoint_moved_off_the_rolling_window():
    """Scope guard: the other whole-day endpoints are far smaller (dam_lambda is 24
    rows/day), so they keep the rolling window."""
    assert backfill.DAILY_SETTLED == ("dam_spp",)
