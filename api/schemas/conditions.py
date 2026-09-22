"""Schemas served by the conditions range route."""

from datetime import datetime

from pydantic import BaseModel

# ---- /conditions_range -------------------------------------------------------
#
# Per-hour DAM-close Conditions. Every value is from the latest source
# publication available by 10:00 CT on D-1, so all Map views share it.
# Load/Wind/Solar are forecasts. Outages are expected unavailable MW by fuel,
# including units already reported out when the DAM closed.


class ZoneLoad(BaseModel):
    zone: str
    dam_close_mw: float | None


class RegionGen(BaseModel):
    region: str
    dam_close_mw: float | None


class FuelOutage(BaseModel):
    fuel: str
    dam_close_mw: float | None


class ConditionsEntry(BaseModel):
    interval_ts: datetime
    load: list[ZoneLoad]
    wind: list[RegionGen]
    solar: list[RegionGen]
    outages: list[FuelOutage]


class ConditionsRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ConditionsEntry]
