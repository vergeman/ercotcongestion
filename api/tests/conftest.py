"""Test fixtures: fake DB pool that returns canned rows.

Avoids requiring a live Postgres for unit tests. Integration tests against the
real DB live elsewhere.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, '/api')


from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import db as db_module
from main import app


class FakeCursor:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []
        self.responses: list[list[tuple]] = []

    def queue(self, rows: list[tuple]) -> None:
        self.responses.append(rows)

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.queries.append((sql, params))

    def fetchone(self):
        if not self.responses:
            return None
        rows = self.responses.pop(0)
        return rows[0] if rows else None

    def fetchall(self):
        if not self.responses:
            return []
        return self.responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self, *args, **kwargs):
        # Accept and ignore row_factory= and other psycopg cursor kwargs;
        # tests queue rows as whatever shape the production code expects
        # (dicts, since routes use dict_row).
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakePool:
    def __init__(self):
        self.cursor = FakeCursor()

    @contextmanager
    def connection(self):
        yield FakeConn(self.cursor)


@pytest.fixture
def fake_pool(monkeypatch):
    """Replace the module-level pool with a FakePool; return it for queueing rows."""
    pool = FakePool()
    monkeypatch.setattr(db_module, 'pool', pool)
    return pool


@pytest.fixture
def client(fake_pool):
    """TestClient that bypasses the real lifespan (so we don't open a real pool)."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.router.lifespan_context = original


@pytest.fixture
def ts_utc():
    return datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
