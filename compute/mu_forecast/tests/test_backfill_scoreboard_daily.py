"""Tests for the served daily Scoreboard repair job."""
from __future__ import annotations

from contextlib import nullcontext

import pytest

import compute.jobs.backfill_scoreboard_daily as job


class Conn:
    def __init__(self):
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        self.commits += 1


def _rows():
    return [{"source": str(i)} for i in range(5)]


def _connect(conns):
    def connect():
        conn = Conn()
        conns.append(conn)
        return conn
    return connect


def test_dry_run_does_not_persist(monkeypatch):
    conns, persisted = [], []
    monkeypatch.setattr(job, "_existing_rows", lambda *args: 3)
    monkeypatch.setattr(job, "grade_day", lambda *args, **kwargs: _rows())
    monkeypatch.setattr(job, "persist_grades", lambda *args: persisted.append(args))
    summary = job.backfill_range(_connect(conns), run_id="r", horizon=1,
                                  start="2025-01-01", end="2025-01-02")
    assert summary.dry_run == ["2025-01-01", "2025-01-02"]
    assert not persisted
    assert [conn.commits for conn in conns] == [0, 0]


def test_write_replaces_existing_or_materializes_new_rows(monkeypatch):
    conns, persisted = [], []
    monkeypatch.setattr(job, "_existing_rows", lambda conn, run_id, D, horizon:
                        5 if str(D.date()) == "2025-01-01" else 0)
    monkeypatch.setattr(job, "grade_day", lambda *args, **kwargs: _rows())
    monkeypatch.setattr(job, "persist_grades", lambda *args: persisted.append(args))
    summary = job.backfill_range(_connect(conns), run_id="r", horizon=2,
                                  start="2025-01-01", end="2025-01-02", to_db=True)
    assert summary.replaced == ["2025-01-01"]
    assert summary.newly_materialized == ["2025-01-02"]
    assert len(persisted) == 2
    assert [conn.commits for conn in conns] == [1, 1]


def test_failures_continue_or_stop_without_persisting_that_key(monkeypatch):
    conns, persisted = [], []
    monkeypatch.setattr(job, "_existing_rows", lambda *args: 5)
    def grade(conn, D, **kwargs):
        if str(D.date()) == "2025-01-02":
            raise RuntimeError("no served SF artifact")
        return _rows()
    monkeypatch.setattr(job, "grade_day", grade)
    monkeypatch.setattr(job, "persist_grades", lambda *args: persisted.append(args))
    summary = job.backfill_range(_connect(conns), run_id="r", horizon=1,
                                  start="2025-01-01", end="2025-01-03", to_db=True)
    assert summary.replaced == ["2025-01-01", "2025-01-03"]
    assert summary.missing_artifact == ["2025-01-02"]
    assert len(persisted) == 2

    conns.clear()
    persisted.clear()
    summary = job.backfill_range(_connect(conns), run_id="r", horizon=1,
                                  start="2025-01-01", end="2025-01-03", to_db=True,
                                  stop_on_error=True)
    assert summary.replaced == ["2025-01-01"]
    assert summary.missing_artifact == ["2025-01-02"]
    assert summary.stopped and len(persisted) == 1


def test_rejects_reversed_range():
    with pytest.raises(ValueError, match="start"):
        job.backfill_range(lambda: nullcontext(), run_id="r", horizon=1,
                           start="2025-01-03", end="2025-01-01")


def test_rerun_replaces_the_same_key(monkeypatch):
    conns, persisted = [], []
    monkeypatch.setattr(job, "_existing_rows", lambda *args: 5)
    monkeypatch.setattr(job, "grade_day", lambda *args, **kwargs: _rows())
    monkeypatch.setattr(job, "persist_grades", lambda *args: persisted.append(args))
    for _ in range(2):
        summary = job.backfill_range(_connect(conns), run_id="r", horizon=1,
                                      start="2025-01-01", end="2025-01-01", to_db=True)
        assert summary.replaced == ["2025-01-01"]
    assert len(persisted) == 2
