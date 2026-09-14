from __future__ import annotations

import numpy as np
import pandas as pd

from compute.projection.codecs import build_sf_window_artifact
from compute.sf_map.geography import persist
from compute.sf_map.storage.maps import load_window_sf


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, _query, params):
        self.params = params

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return None if not self.rows else self.rows[0]


class _Connection:
    def __init__(self, rows):
        self.cursor_ = _Cursor(rows)

    def cursor(self):
        return self.cursor_


def test_load_window_sf_applies_legacy_threshold_and_fill_modes():
    sf = pd.DataFrame([[0.4, -0.2], [0.1, 0.0001]],
                      index=["c1", "c2"], columns=["sp1", "sp2"])
    conn = _Connection([(build_sf_window_artifact(sf),)])

    dense = load_window_sf(conn, "map-v1", "2026-01-01")
    sparse = load_window_sf(conn, "map-v1", "2026-01-01", fill_value=None)

    assert dense.loc["c2", "sp2"] == 0.0
    assert np.isnan(sparse.loc["c2", "sp2"])
    assert conn.cursor_.params == ("map-v1", pd.Timestamp("2026-01-01"))


def test_load_window_sf_empty_result_stays_empty_in_sparse_mode():
    assert load_window_sf(_Connection([]), "map-v1", "2026-01-01", fill_value=None).empty


class _ManagedConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def commit(self):
        pass


def test_geography_requests_sparse_sf_and_passes_it_to_window_geo(monkeypatch):
    conn = _ManagedConnection()
    window_start = pd.Timestamp("2026-01-01")
    window_end = pd.Timestamp("2026-01-08")
    sparse = pd.DataFrame([[0.4, np.nan]], index=["c1"], columns=["sp1", "sp2"])
    seen = {}

    monkeypatch.setattr(persist.psycopg, "connect", lambda _dsn: conn)
    monkeypatch.setattr(persist, "load_sp_geography", lambda: pd.DataFrame())
    monkeypatch.setattr(persist, "_load_windows", lambda *_: [(window_start, window_end)])
    monkeypatch.setattr(
        persist, "load_shadow_prices",
        lambda *_: pd.DataFrame(index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(persist, "delete_constraint_geo", lambda *_: 0)

    def fake_load(conn_, run_id, start, *, fill_value):
        seen["load"] = (conn_, run_id, start, fill_value)
        return sparse

    def fake_window_geo(SF, _sp, _Mw):
        seen["SF"] = SF
        return pd.DataFrame({"spread_km": np.nan}, index=SF.index)

    monkeypatch.setattr(persist, "load_window_sf", fake_load)
    monkeypatch.setattr(persist, "_window_geo", fake_window_geo)
    monkeypatch.setattr(persist, "copy_constraint_geo_rows", lambda *_: 1)

    assert persist.main(["--run-id", "map-v1"]) == 0
    assert seen["load"] == (conn, "map-v1", window_start, None)
    assert seen["SF"] is sparse
