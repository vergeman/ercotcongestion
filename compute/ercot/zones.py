"""ERCOT weather-zone labels — the eight NP3-561/NP6-345 weather zones.

A standalone tuple so covariate code can reference the zone labels without
pulling in any OPF/congestion stack.
"""
from __future__ import annotations

WEATHER_ZONES = (
    'coast', 'east', 'far_west', 'north',
    'north_central', 'south_central', 'southern', 'west',
)
