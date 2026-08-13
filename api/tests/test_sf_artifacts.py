"""Unit tests for shared immutable SF+μ artifact serving helpers."""
from __future__ import annotations

from datetime import date

import pandas as pd

from compute.sf.project import SfMuArtifact, build_sf_mu_artifact
from services import sf_artifacts as sa
from services.sf_artifacts import SfArtifactCache, normalize_constraint_key


def _artifact(value: float) -> SfMuArtifact:
    return SfMuArtifact(
        SF=pd.DataFrame([[value]], index=["C|BASE"], columns=["SP"]),
        E_mu=pd.DataFrame([[value]], index=pd.to_datetime(["2026-07-01T00:00Z"]),
                          columns=["C|BASE"]),
    )


def _blob(value: float) -> bytes:
    """A real SF+μ npz whose single SF cell is `value`, so a decoded artifact is
    identifiable by which blob it came from."""
    return build_sf_mu_artifact(
        pd.DataFrame([[value]], index=["C|BASE"], columns=["SP"]).astype("f4"),
        pd.DataFrame([[value]], index=pd.to_datetime(["2026-07-01T00:00Z"]),
                     columns=["C|BASE"]).astype("f4"),
    )


def _sf_val(art: SfMuArtifact) -> float:
    return float(art.SF.to_numpy().ravel()[0])


class _Cur:
    """Minimal FIFO cursor: queue the rows each query returns, in order."""
    def __init__(self):
        self._responses: list = []

    def queue(self, row):
        self._responses.append(row)

    def execute(self, sql, params=()):
        pass

    def fetchone(self):
        return self._responses.pop(0) if self._responses else None


def test_normalize_constraint_key_trims_only_outer_whitespace():
    assert normalize_constraint_key("  C North  ", " BASE CASE ") == "C North|BASE CASE"


def test_load_realized_mu_keeps_unmatched_keys_absent_for_display_consumers():
    class Cur:
        def __init__(self):
            self.sql = ""

        def execute(self, sql, params=()):
            self.sql = sql

        def fetchall(self):
            return [
                {"constraint_name": " A ", "contingency_name": " BASE ", "shadow_price": 2.5},
                {"constraint_name": "A", "contingency_name": "BASE", "shadow_price": 1.5},
                {"constraint_name": "OTHER", "contingency_name": "BASE", "shadow_price": 9.0},
            ]

    cur = Cur()
    mu = sa.load_realized_mu(cur, pd.to_datetime(["2026-07-01T05:00Z"]), ["A|BASE", "B|BASE"])
    assert mu.to_dict() == {"A|BASE": 4.0}
    assert "DISTINCT ON" in cur.sql and "dst_flag ASC" in cur.sql


def test_cache_keys_include_run_delivery_day_and_horizon():
    """The cache key carries horizon (0123), so a day's final and preview artifacts
    live in separate slots and never alias."""
    cache = SfArtifactCache()
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    a, b, c, e = _artifact(1.0), _artifact(2.0), _artifact(3.0), _artifact(4.0)
    cache.put(("run-a", d1, 1), a)
    cache.put(("run-b", d1, 1), b)
    cache.put(("run-a", d2, 1), c)
    cache.put(("run-a", d1, 2), e)          # same run+day, preview track

    assert cache.get(("run-a", d1, 1)) is a
    assert cache.get(("run-b", d1, 1)) is b
    assert cache.get(("run-a", d2, 1)) is c
    assert cache.get(("run-a", d1, 2)) is e  # preview does not alias the final


def test_load_daily_artifact_coalesces_prefer_final():
    """Default lookup serves the final (horizon 1) when one exists — the min(horizon)
    probe resolves 1, and only that track's blob is fetched."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    cur.queue({"h": 1})                     # min(horizon) probe
    cur.queue({"sf_npz": _blob(1.0)})       # horizon-1 blob
    assert _sf_val(sa.load_daily_artifact(cur, "m", date(2026, 8, 1))) == 1.0


def test_load_daily_artifact_falls_back_to_preview():
    """Default lookup falls back to the preview (horizon 2) for a preview-only day."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    cur.queue({"h": 2})                     # only the preview exists
    cur.queue({"sf_npz": _blob(2.0)})
    assert _sf_val(sa.load_daily_artifact(cur, "m", date(2026, 8, 2))) == 2.0


def test_load_daily_artifact_missing_day_is_none():
    """No artifact for the day (neither horizon) → None, no blob fetch."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    cur.queue({"h": None})                  # min(horizon) over an empty set
    assert sa.load_daily_artifact(cur, "m", date(2026, 8, 3)) is None


def test_explicit_horizon_reads_that_track_and_404_maps_to_none():
    """An explicit horizon skips the probe and reads exactly that track; absent → None
    (the caller turns that into a 404)."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    cur.queue({"sf_npz": _blob(2.0)})       # no probe when horizon is explicit
    assert _sf_val(sa.load_daily_artifact(cur, "m", date(2026, 8, 4), horizon=2)) == 2.0

    cur.queue(None)                         # horizon-1 blob absent
    assert sa.load_daily_artifact(cur, "m", date(2026, 8, 4), horizon=1) is None


def test_final_and_preview_cache_independently():
    """The two horizons of one day cache under distinct keys, so serving one never
    returns the other."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    d = date(2026, 9, 1)
    cur.queue({"sf_npz": _blob(1.0)})
    a1 = sa.load_daily_artifact(cur, "m", d, horizon=1)
    cur.queue({"sf_npz": _blob(2.0)})
    a2 = sa.load_daily_artifact(cur, "m", d, horizon=2)
    assert _sf_val(a1) == 1.0 and _sf_val(a2) == 2.0
    assert _sf_val(sa._ARTIFACT_CACHE.get(("m", d, 1))) == 1.0
    assert _sf_val(sa._ARTIFACT_CACHE.get(("m", d, 2))) == 2.0
