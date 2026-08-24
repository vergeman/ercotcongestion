from datetime import date

import pandas as pd

from compute.jobs.forecast_history import persist_rollup, rollup_rows
from compute.projection.propagate import SfMuArtifact


def _artifact():
    return SfMuArtifact(
        SF=pd.DataFrame([[1.0], [2.0]], index=["A|x", "B|y"], columns=["SP"]),
        E_mu=pd.DataFrame([[1.5, 0.0], [2.5, -3.0], [0.0, 0.0]],
                          columns=["A|x", "B|y"]),
    )


def test_rollup_rows_keeps_every_untruncated_artifact_key_and_binding_hours():
    assert rollup_rows(_artifact()) == [("A|x", 4.0, 2), ("B|y", -3.0, 1)]


class Cursor:
    def __init__(self):
        self.sql = self.rows = None

    def executemany(self, sql, rows):
        self.sql, self.rows = sql, list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Conn:
    def __init__(self):
        self.cur = Cursor()

    def cursor(self):
        return self.cur


def test_persist_rollup_is_keyed_like_the_artifact_and_upserts_in_place():
    conn = Conn()
    assert persist_rollup(conn, "mu-v1", date(2026, 7, 28), 1, _artifact()) == 2
    assert conn.cur.rows == [
        ("mu-v1", date(2026, 7, 28), 1, "A|x", 4.0, 2),
        ("mu-v1", date(2026, 7, 28), 1, "B|y", -3.0, 1),
    ]
    assert "ON CONFLICT (run_id, delivery_date, horizon, constraint_key)" in conn.cur.sql
