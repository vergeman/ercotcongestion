"""ERCOT weather-zone labels — the eight NP3-561/NP6-345 weather zones.

Extracted from ``ercot.transforms`` (now frozen under ``compute.legacy``) so the
kept graph (``regimes`` → μ-model covariates) can reference the zone tuple
without pulling in the OPF/congestion stack that ``transforms`` depends on.
"""
from __future__ import annotations

WEATHER_ZONES = (
    'coast', 'east', 'far_west', 'north',
    'north_central', 'south_central', 'southern', 'west',
)
