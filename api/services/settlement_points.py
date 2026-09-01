"""Cached settlement-point geography and display metadata."""

from __future__ import annotations

import logging

import pandas as pd

from shared.settings import settings

log = logging.getLogger(__name__)

_COORDINATES: dict[str, tuple[float, float]] | None = None
_METADATA: dict[str, tuple[str | None, str | None]] | None = None


def coordinates() -> dict[str, tuple[float, float]]:
    global _COORDINATES
    if _COORDINATES is None:
        try:
            frame = pd.read_csv(settings.settlement_points_geocoded_csv)
        except FileNotFoundError:
            log.warning("settlement_points geocoded csv missing; coordinates empty")
            _COORDINATES = {}
        else:
            frame = frame.dropna(subset=["lat", "lon"])
            _COORDINATES = {
                str(row.settlement_point): (float(row.lat), float(row.lon))
                for row in frame.itertuples(index=False)
            }
    return _COORDINATES


def metadata() -> dict[str, tuple[str | None, str | None]]:
    global _METADATA
    if _METADATA is None:
        try:
            frame = pd.read_csv(settings.settlement_points_geocoded_csv)
        except FileNotFoundError:
            log.warning("settlement_points geocoded csv missing; metadata empty")
            _METADATA = {}
        else:
            _METADATA = {
                str(row.settlement_point): (
                    (
                        None
                        if pd.isna(getattr(row, "sp_type", None))
                        else str(getattr(row, "sp_type"))
                    ),
                    (
                        None
                        if pd.isna(getattr(row, "load_zone", None))
                        else str(getattr(row, "load_zone"))
                    ),
                )
                for row in frame.itertuples(index=False)
            }
    return _METADATA


def clear_cache() -> None:
    """Clear process caches; intended for focused tests."""
    global _COORDINATES, _METADATA
    _COORDINATES = None
    _METADATA = None
