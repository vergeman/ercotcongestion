"""Schemas shared by multiple API workspaces."""

from datetime import date

from pydantic import BaseModel

# ---- /scoreboard/summary --------------------------------------------------

class BootstrapSectionStatus(BaseModel):
    """Availability and source identity for one independently built section."""
    available: bool
    unavailable_reason: str | None = None
    run_id: str | None = None
    delivery_date: date | None = None
    horizon: int | None = None
