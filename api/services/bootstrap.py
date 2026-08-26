"""Shared helpers for independently available bootstrap sections."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException


T = TypeVar("T")


def soft_fail(build: Callable[[], T]) -> T | None:
    """Convert a section's source-unavailable 503 into an absent section."""
    try:
        return build()
    except HTTPException as exc:
        if exc.status_code == 503:
            return None
        raise


def availability_status(section: object | None, status_type):
    """Build the common availability payload without making null ambiguous."""
    if section is None:
        return status_type(available=False, unavailable_reason="source_unavailable")
    return status_type(
        available=True,
        run_id=getattr(section, "run_id", None),
        delivery_date=getattr(section, "delivery_date", None),
        horizon=getattr(section, "horizon", None),
    )
