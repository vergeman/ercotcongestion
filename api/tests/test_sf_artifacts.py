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


def _hourly_blob(start: str, count: int) -> bytes:
    """A real SF+μ npz with `count` hourly rows starting at `start` (UTC ISO)."""
    hours = pd.date_range(start, periods=count, freq="h", tz="UTC")
    return build_sf_mu_artifact(
        pd.DataFrame([[1.0]], index=["C|BASE"], columns=["SP"]).astype("f4"),
        pd.DataFrame([[1.0]] * count, index=hours, columns=["C|BASE"]).astype("f4"),
    )


def test_artifact_tail_stitches_todays_full_day_with_tomorrows_final():
    """D's own 24 UTC hours plus D+1's final tail cover the whole CT day."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    d = date(2026, 8, 15)
    cur.queue({"sf_npz": _hourly_blob("2026-08-15T00:00Z", 24)})  # today, horizon=1 explicit
    cur.queue({"h": 1})                                           # tomorrow probe: final exists
    cur.queue({"sf_npz": _hourly_blob("2026-08-16T00:00Z", 24)})  # tomorrow, horizon=1

    tail = sa.load_daily_artifact_tail(cur, "m", d, 1)

    assert tail is not None
    assert tail.tomorrow is not None
    assert tail.tail_horizon is None            # same horizon as today — not a mixed stitch
    assert tail.hours_expected == 24
    assert tail.hours_covered == 24              # 19 from today + 5 evening hours from tomorrow


def test_artifact_tail_borrows_preview_when_final_tail_is_not_landed_yet():
    """An h1 day borrows its evening tail from D+1's h2 preview (cross-horizon fallback)."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    d = date(2026, 8, 15)
    cur.queue({"sf_npz": _hourly_blob("2026-08-15T00:00Z", 24)})  # today, horizon=1 explicit
    cur.queue({"h": 2})                                           # tomorrow probe: only preview exists
    cur.queue({"sf_npz": _hourly_blob("2026-08-16T00:00Z", 24)})  # tomorrow, horizon=2

    tail = sa.load_daily_artifact_tail(cur, "m", d, 1)

    assert tail is not None
    assert tail.tomorrow is not None
    assert tail.tail_horizon == 2                # mixed vintage: today=1, tomorrow=2
    assert tail.hours_covered == 24


def test_artifact_tail_truncates_when_tomorrow_has_no_artifact_at_any_horizon():
    """No D+1 artifact at all → D alone, truncated to its own UTC-day hours."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    d = date(2026, 8, 15)
    cur.queue({"sf_npz": _hourly_blob("2026-08-15T00:00Z", 24)})  # today, horizon=1 explicit
    cur.queue({"h": None})                                        # tomorrow probe: nothing at all

    tail = sa.load_daily_artifact_tail(cur, "m", d, 1)

    assert tail is not None
    assert tail.tomorrow is None
    assert tail.tail_horizon is None
    assert tail.hours_expected == 24
    assert tail.hours_covered == 19               # today's UTC-day hours land inside the CT day


def test_artifact_tail_is_none_when_todays_own_artifact_is_missing():
    """D's own artifact at the resolved horizon is still non-negotiable."""
    sa._ARTIFACT_CACHE.clear()
    cur = _Cur()
    cur.queue(None)  # today, horizon=1 explicit — absent

    assert sa.load_daily_artifact_tail(cur, "m", date(2026, 8, 15), 1) is None


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
