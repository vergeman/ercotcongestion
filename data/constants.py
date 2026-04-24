"""
constants.py
EIA-860 fuel code -> canonical carrier name / "Fuel Type"
"""

EIA_TO_CARRIER = {
    # Natural Gas
    'NG':  'gas',
    'LFG': 'gas',   # landfill gas
    'OG':  'gas',   # other gas

    # Coal
    'BIT': 'coal',  # bituminous
    'SUB': 'coal',  # subbituminous
    'LIG': 'coal',  # lignite
    'RC':  'coal',  # refined coal

    # Oil
    'DFO': 'oil',   # distillate fuel oil
    'RFO': 'oil',   # residual fuel oil
    'JF':  'oil',   # jet fuel
    'KER': 'oil',   # kerosene

    # Renewables
    'WND': 'wind',
    'SUN': 'solar',
    'WAT': 'hydro',
    'GEO': 'geothermal',

    # Other
    'NUC': 'nuclear',
    'MWH': 'battery',
    'WDS': 'biomass',  # wood/wood waste
    'OBL': 'biomass',  # other biomass liquids
    'OBS': 'biomass',  # other biomass solids
    'OBG': 'biomass',  # other biomass gas
    'AB':  'biomass',  # agricultural byproducts
    'MSW': 'biomass',  # municipal solid waste
    'OTH': 'other',
    'PUR': 'other',    # purchased steam
    'WH':  'other',    # waste heat
    'TDF': 'other',    # tire-derived fuel
}


# Derived inverse — carrier → EIA codes (no duplication, always in sync)
from collections import defaultdict
CARRIER_TO_EIA = defaultdict(list)
for eia_code, carrier in EIA_TO_CARRIER.items():
    CARRIER_TO_EIA[carrier].append(eia_code)
CARRIER_TO_EIA['unknown'] = []
CARRIER_TO_EIA = dict(CARRIER_TO_EIA)
