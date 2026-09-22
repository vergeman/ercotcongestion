"""UTC normalization and ERCOT delivery-time constants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from shared.settings import settings
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")


def coerce_utc(ts: datetime) -> datetime:
    """Interpret a naive timestamp as UTC; convert an aware one."""
    return (
        ts.replace(tzinfo=timezone.utc)
        if ts.tzinfo is None
        else ts.astimezone(timezone.utc)
    )


def validate_utc_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Normalize and bound an explicit API range before it reaches the database."""
    start_utc, end_utc = coerce_utc(start), coerce_utc(end)
    if start_utc > end_utc:
        raise HTTPException(status_code=422, detail="start must be at or before end.")
    if end_utc - start_utc > timedelta(hours=settings.max_state_range_hours):
        raise HTTPException(
            status_code=422,
            detail=f"range may not exceed {settings.max_state_range_hours} hours.",
        )
    return start_utc, end_utc


def validate_optional_utc_range(
    start: datetime | None, end: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Allow omitted bounds only when both are omitted for a route default."""
    if start is None and end is None:
        return None, None
    if start is None or end is None:
        raise HTTPException(status_code=422, detail="start and end must be provided together.")
    return validate_utc_range(start, end)
