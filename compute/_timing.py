"""Lightweight perf_counter context manager for snapshot profiling.

Emits one log line per labeled block at INFO level. Cheap enough to leave in.
"""
import logging
import time
from contextlib import contextmanager

_default_logger = logging.getLogger('compute.timing')


@contextmanager
def timed(label: str, logger: logging.Logger | None = None,
          level: int = logging.INFO):
    log = logger or _default_logger
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        log.log(level, f"[timing] {label}: {dt_ms:.1f} ms")
