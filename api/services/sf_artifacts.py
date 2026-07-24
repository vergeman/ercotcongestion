"""Shared access to immutable per-day SF + forecast-μ artifacts.

The database stores one compressed NPZ per ``(run_id, delivery_date)``.  The
decoded object is reused by endpoints that need a dense slice of the day's
causal fit; it is deliberately keyed by both values so a request can never
cross a model-version or delivery-day boundary.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date

from compute.sf.project import SfMuArtifact, load_sf_mu


# A typical decoded daily artifact is roughly 10--20 MiB (dense float32 SF,
# hourly float32 E_mu, and their labels). Keep at most 128 MiB per API worker.
ARTIFACT_CACHE_MAX_BYTES = 128 * 1024 * 1024


def normalize_constraint_key(constraint_name: str, contingency_name: str) -> str:
    """Return the canonical ``constraint|contingency`` key used by SF artifacts."""
    return f"{str(constraint_name).strip()}|{str(contingency_name).strip()}"


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
    """Byte-bounded LRU cache for decoded immutable daily artifacts."""

    def __init__(self, max_bytes: int = ARTIFACT_CACHE_MAX_BYTES) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, date], tuple[SfMuArtifact, int]] = OrderedDict()
        self._bytes = 0

    def get(self, key: tuple[str, date]) -> SfMuArtifact | None:
        item = self._items.get(key)
        if item is None:
            return None
        self._items.move_to_end(key)
        return item[0]

    def put(self, key: tuple[str, date], artifact: SfMuArtifact) -> SfMuArtifact:
        size = _artifact_size_bytes(artifact)
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
        self._items.clear()
        self._bytes = 0


_ARTIFACT_CACHE = SfArtifactCache()


def load_daily_artifact(cur, run_id: str, delivery_date: date) -> SfMuArtifact | None:
    """Fetch and decode a day's artifact, or ``None`` when the blob is absent."""
    key = (run_id, delivery_date)
    cached = _ARTIFACT_CACHE.get(key)
    if cached is not None:
        return cached

    cur.execute(
        "SELECT sf_npz FROM forecast_sf_artifact WHERE run_id = %s AND delivery_date = %s",
        key,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _ARTIFACT_CACHE.put(key, load_sf_mu(bytes(row["sf_npz"])))
