"""UTC normalization and ERCOT delivery-time constants."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


CENTRAL = ZoneInfo("America/Chicago")


def coerce_utc(ts: datetime) -> datetime:
    """Interpret a naive timestamp as UTC; convert an aware one."""
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
