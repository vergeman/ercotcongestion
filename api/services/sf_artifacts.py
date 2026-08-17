"""Shared access to immutable per-day SF + forecast-μ artifacts.

The database stores one compressed NPZ per ``(run_id, delivery_date, horizon)``
(0123: horizon 1 = final/t+1, horizon 2 = preview/t+2).  The decoded object is
reused by endpoints that need a dense slice of the day's causal fit; it is
deliberately keyed by all three values so a request can never cross a
model-version, delivery-day, or horizon boundary.

By default a lookup coalesces per day — it serves the final artifact when one
exists and falls back to the preview otherwise — so a preview-only day is fully
inspectable and, once the final lands, the same request transparently switches to
it.  The transition is handled by resolving the served horizon per request (a cheap
``min(horizon)`` probe) *before* the cache, so the cache never pins a stale preview
for a day that has since been finalized.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date
from threading import Lock

import pandas as pd

from compute.sf.project import SfMuArtifact, load_sf_mu


# A typical decoded daily artifact is roughly 5 MiB (dense float32 SF, hourly
# float32 E_mu, and their labels). Sized so a single request's trailing-30-day
# node-history window (31 artifacts ~= 150 MiB) fits without thrashing, which is
# what let /analysis/standouts warm across a multi-day Brief page load (0137).
ARTIFACT_CACHE_MAX_BYTES = 256 * 1024 * 1024


def normalize_constraint_key(constraint_name: str, contingency_name: str) -> str:
    """Return the canonical ``constraint|contingency`` key used by SF artifacts."""
    return f"{str(constraint_name).strip()}|{str(contingency_name).strip()}"


def load_realized_mu(cur, timestamps, constraint_keys) -> pd.Series:
    """Sum published DAM μ over artifact hours, aligned to its key vocabulary.

    This is the realized counterpart to an artifact's ``E_mu.sum(axis=0)``.
    Both Matrix's exact-hour display and the brief's multi-hour attribution use
    it, so key normalization and the non-DST duplicate preference cannot drift.
    Missing DAM constraints are omitted; consumers that need a full arithmetic
    vector explicitly reindex and fill zero, while display consumers retain the
    important distinction between an unmatched price and a published zero.
    """
    keys = set(str(key) for key in constraint_keys)
    values: dict[str, float] = {}
    hours = list(pd.DatetimeIndex(timestamps).to_pydatetime())
    if not hours:
        return pd.Series(dtype=float)
    cur.execute(
        "SELECT DISTINCT ON (interval_ts, constraint_name, contingency_name) "
        "interval_ts, constraint_name, contingency_name, shadow_price "
        "FROM ercot_dam_shadow_prices "
        "WHERE interval_ts = ANY(%s) AND shadow_price IS NOT NULL "
        "ORDER BY interval_ts, constraint_name, contingency_name, dst_flag ASC",
        (hours,),
    )
    for row in cur.fetchall():
        key = normalize_constraint_key(row["constraint_name"], row["contingency_name"])
        if key in keys:
            values[key] = values.get(key, 0.0) + float(row["shadow_price"])
    return pd.Series(values, dtype=float)


def _artifact_size_bytes(artifact: SfMuArtifact) -> int:
    """Conservative in-memory size accounting for cache eviction."""
    return int(
        artifact.SF.to_numpy().nbytes
        + artifact.E_mu.to_numpy().nbytes
        + artifact.SF.index.memory_usage(deep=True)
        + artifact.SF.columns.memory_usage(deep=True)
        + artifact.E_mu.index.memory_usage(deep=True)
    )


class SfArtifactCache:
    """Byte-bounded LRU cache for decoded immutable daily artifacts.

    Lock-guarded: composed endpoints run their sections in a thread pool, and a
    reload fires several such requests at once, so ``get``/``put``/evict are
    touched concurrently — an unguarded ``OrderedDict`` corrupts its byte
    accounting and links under that (0137)."""

    def __init__(self, max_bytes: int = ARTIFACT_CACHE_MAX_BYTES) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, date, int], tuple[SfMuArtifact, int]] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def get(self, key: tuple[str, date, int]) -> SfMuArtifact | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return item[0]

    def put(self, key: tuple[str, date, int], artifact: SfMuArtifact) -> SfMuArtifact:
        size = _artifact_size_bytes(artifact)
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old[1]
            self._items[key] = (artifact, size)
            self._bytes += size
            while self._bytes > self.max_bytes and len(self._items) > 1:
                _, (_, evicted_size) = self._items.popitem(last=False)
                self._bytes -= evicted_size
        return artifact

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0


_ARTIFACT_CACHE = SfArtifactCache()


def resolve_daily_horizon(cur, run_id: str, delivery_date: date) -> int | None:
    """Return the horizon ``load_daily_artifact(..., horizon=None)`` would serve.

    A cheap ``min(horizon)`` probe: 1 (final) when it exists, else 2 (preview),
    else ``None`` when the day has no artifact at any horizon.
    """
    cur.execute(
        "SELECT min(horizon) AS h FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s",
        (run_id, delivery_date),
    )
    row = cur.fetchone()
    return None if row is None or row["h"] is None else int(row["h"])


def load_daily_artifact(cur, run_id: str, delivery_date: date,
                        horizon: int | None = None) -> SfMuArtifact | None:
    """Fetch and decode a day's artifact, or ``None`` when the blob is absent.

    ``horizon=None`` (the default) coalesces per day: it serves the final artifact
    (horizon 1) when one exists and falls back to the preview (horizon 2) otherwise.
    An explicit ``horizon`` reads exactly that track — used to inspect a preserved
    preview for a day that already has a final (0123).

    The served horizon is resolved *before* the cache via a cheap ``min(horizon)``
    probe, so the cache is keyed by the concrete horizon and never returns a stale
    preview for a day that has since been finalized.
    """
    if horizon is None:
        horizon = resolve_daily_horizon(cur, run_id, delivery_date)
        if horizon is None:
            return None

    key = (run_id, delivery_date, horizon)
    cached = _ARTIFACT_CACHE.get(key)
    if cached is not None:
        return cached

    cur.execute(
        "SELECT sf_npz FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
        (run_id, delivery_date, horizon),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _ARTIFACT_CACHE.put(key, load_sf_mu(bytes(row["sf_npz"])))


def load_daily_artifacts(cur, run_id: str, delivery_dates: list[date],
                         horizon: int) -> dict[date, SfMuArtifact]:
    """Cache-aware batch load of several days' artifacts at an explicit horizon.

    Replaces a per-day ``load_daily_artifact`` loop's N single-row round trips
    with one windowed fetch of the cache misses (0137). Unlike the coalescing
    single-day path this takes an explicit ``horizon`` only — callers pass an
    already-resolved horizon — so a day lacking that track is simply absent from
    the result (the SELECT skips it), matching the loop's ``None`` -> skip.
    """
    result: dict[date, SfMuArtifact] = {}
    missing: list[date] = []
    for day in delivery_dates:
        cached = _ARTIFACT_CACHE.get((run_id, day, horizon))
        if cached is not None:
            result[day] = cached
        else:
            missing.append(day)
    if missing:
        cur.execute(
            "SELECT delivery_date, sf_npz FROM forecast_sf_artifact "
            "WHERE run_id = %s AND horizon = %s AND delivery_date = ANY(%s)",
            (run_id, horizon, missing),
        )
        for row in cur.fetchall():
            day = row["delivery_date"]
            result[day] = _ARTIFACT_CACHE.put(
                (run_id, day, horizon), load_sf_mu(bytes(row["sf_npz"])))
    return result
