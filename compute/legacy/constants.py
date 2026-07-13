# ============================================================================
# Constants
# ============================================================================

IRR_CARRIERS = ('wind', 'solar', 'battery')
THERMAL_CARRIERS = ('gas', 'coal', 'nuclear', 'oil', 'biomass', 'hydro')

# Carrier-level availability ceilings for non-renewable carriers
# NB: These are fallback values
DEFAULT_P_MAX_PU: dict[str, float] = {
    'battery': 0.25,   # arbitrary SOC proxy — not a true availability signal
    'nuclear': 0.95,
    'hydro':   0.50,
    'coal':    0.90,
    'gas':     0.90,
    'oil':     0.80,
    'biomass': 0.80,
    'other':   0.80,
}

SHED_COST = 5000   # ERCOT offer cap; (VOLL: Value of Lost Load)
SHED_PREFIX = "shed_"   # prefix for load-shed pseudo-generators in n.generators.index

PV_REGIONS = ('centerwest', 'northwest', 'farwest', 'fareast', 'southeast', 'centereast')
WIND_REGIONS = ('panhandle', 'coastal', 'south', 'west', 'north')
LOAD_ZONES = ('houston', 'north', 'south', 'west')
