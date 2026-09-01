"""Schemas served by the conditions range route."""

from datetime import datetime

from pydantic import BaseModel

# ---- /conditions_range -------------------------------------------------------
#
# Per-hour Load / Wind / Solar / Outages, in one response. Each sub-list
# carries both `forecast_mw` and `actual_mw` per row so a single Conditions row
# can pick either side client-side (the map's Forecast/ Market/Compare/Error
# toggle), with no per-side request or client-side merge.
#
# load   actual (NP6-345-CD, `load_by_zone`) alongside forecast (NP3-561-CD,
#        `load_forecast_zonal`, read at the latest vintage posted no later
#        than `interval_ts` — no lookahead). `zone` is one of the 8 weather
#        zones in `compute.ercot.zones.WEATHER_ZONES`, plus `"system"`.
#
# wind/solar
#        actual (NP4-732-CD / NP4-737-CD, `wind_hourly_regional` /
#        `solar_hourly_regional`) alongside forecast (`wind_forecast_regional`
#        / `solar_forecast_regional`, STWPF/STPPF, same no-lookahead vintage
#        rule).
#
# outages
#        DIFFERENT quantity from wind/solar: MW currently OFFLINE (NP1-346
#        unplanned resource outages), not MW produced — and a different cadence
#        underneath: `resource_outages` is a daily D-vintage snapshot, not an
#        hourly series, so a day's values repeat across its 24 hourly entries.
#        `fuel` is one of gas/wind/solar/coal/other/hydro, plus `"total"`.
#        `forecast_mw`, `actual_mw` is the newest vintage through the day
#        itself, summed over genuinely-active-at-that-hour events.


class ZoneLoad(BaseModel):
    zone: str
    forecast_mw: float | None
    actual_mw: float | None


class RegionGen(BaseModel):
    region: str
    forecast_mw: float | None
    actual_mw: float | None


class FuelOutage(BaseModel):
    fuel: str
    forecast_mw: float | None
    actual_mw: float | None


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
