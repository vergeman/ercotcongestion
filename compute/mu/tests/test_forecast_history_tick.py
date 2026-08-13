import compute.jobs.daily_forecast as daily_forecast
import pandas as pd


D = pd.Timestamp("2026-07-28", tz="UTC")


class Conn:
    def __init__(self):
        self.commits = self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_forecast_history_tick_appends_the_published_artifact(monkeypatch):
    conn = Conn()
    artifact = object()
    seen = []
    monkeypatch.setattr(daily_forecast, "load_artifact", lambda *_: artifact)
    monkeypatch.setattr(daily_forecast, "persist_rollup",
                        lambda *args: seen.append(args) or 17)

    daily_forecast._forecast_history_latest(conn, "mu-v1", D, 1)

    assert seen == [(conn, "mu-v1", D.date(), 1, artifact)]
    assert conn.commits == 1 and conn.rollbacks == 0


def test_forecast_history_tick_failure_cannot_fail_an_already_published_forecast(monkeypatch):
    conn = Conn()
    monkeypatch.setattr(daily_forecast, "load_artifact", lambda *_: object())
    monkeypatch.setattr(daily_forecast, "persist_rollup",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("db down")))

    daily_forecast._forecast_history_latest(conn, "mu-v1", D, 1)

    assert conn.commits == 0 and conn.rollbacks == 1
