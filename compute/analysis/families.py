"""Shared settlement-point classification constants.

The legacy brief finding families were removed with the precomputed blob.  This
module remains because ``metadata`` still needs the canonical exclusions when
deriving hub types from settlement-point names.
"""

# ``*AVG`` hubs are aggregates, not tradable locations.
HUB_AVG_EXCLUDE = frozenset({"HB_BUSAVG", "HB_HUBAVG"})
