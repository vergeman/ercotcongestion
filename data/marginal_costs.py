"""marginal_costs.py

Sources:

Fuel prices: EIA Electric Power Annual 2024
https://www.eia.gov/electricity/annual/
https://www.eia.gov/electricity/monthly/

Heat rates:  EIA Electric Power Annual 2024, Tables 8.1, 8.2
https://www.eia.gov/electricity/annual/table.php?t=epa_08_01.html
https://www.eia.gov/electricity/annual/table.php?t=epa_08_02.html

  * Heat Rate: measure of generator inefficiency (lower is better, less fuel wasted as heat)

      heat rate (MMBtu/MWh) *  fuel price ($/MMBTU) = marginal cost ($/MWh)

      Any price lower than marginal cost, plant loses money operating

      Perfect conversion:  3.412 MMBtu/MWh:
      Combined cycle gas:  7.0   MMBtu/MWh
      Simple cycle gas:    10.5  MMBtu/MWh
      Coal steam:          10.0  MMBtu/MWh
      Nuclear:             10.5  MMBtu/MWh  - maybe more inefficient but has cheap fuel


  * Future - Plant-level: EIA-923 (fuel consumption + generation →
    back-calculated heat rates): https://www.eia.gov/electricity/data/eia923/


VOM Adders:  Variable O&M assumptions
AEO2025 VOM Table 3: https://www.eia.gov/outlooks/aeo/assumptions/pdf/EMM_Assumptions.pdf

"""

from pathlib import Path
import pandas as pd
import pypsa

NETWORK_PATH = Path("/data/processed/Texas2k_series25_case1_summerpeak.nc")
OUTPUT_PATH  = Path("/data/processed/marginal_costs.csv")

# EIA average fuel prices $/MMBtu TX
# Source: EIA Electric Power Annual 2024 (Tables 7.17-7.20) +
#         Electric Power Monthly YTD 2025 (Tables 4.10-4.13)
FUEL_PRICE = {
    'gas':        3.20,
    'coal':       2.20,
    'oil':        17.0,
    'nuclear':    0.75,
    'wind':       0.00,   # no "fuel" consumed
    'solar':      0.00,
    'hydro':      0.00,
    'battery':    0.00,
    'biomass':    3.00,
    'other':      5.00,
    'unknown':    5.00,
}


# Source: EIA Electric Power Annual 2024, Tables 8.1  (US avg Operating Heat Rate, 2024)
# Units: MMBtu/MWh (= thousand Btu/kWh / 1000)
HEAT_RATE = {
    'gas':        7.75,   # average across CC: Combined Cycle 7.5, CT - Combustion Turbine: 9.8-10.5
    'coal':       10.78,
    'oil':        11.20,
    'nuclear':    10.44,
    'wind':       0.0,
    'solar':      0.0,
    'hydro':      0.0,
    'battery':    0.0,
    'biomass':    13.5,
    'other':      10.0,
    'unknown':    10.0,
}

# Variable O&M adder $/MWh — captures non-fuel variable costs
VOM_ADDER = {
    'gas':        3.75,
    'coal':       5.3,
    'oil':        5.5,
    'nuclear':    2.62,
    'wind':       0.0,
    'solar':      0.0,
    'hydro':      1.71,
    'battery':    0.0,
    'biomass':    5.93,
    'other':      5.0,
    'unknown':    5.0,
}


def compute_marginal_costs(n):
    df = n.generators[['bus', 'carrier', 'p_nom']].copy()

    df['fuel_price'] = df['carrier'].map(FUEL_PRICE).fillna(FUEL_PRICE['unknown'])
    df['heat_rate']  = df['carrier'].map(HEAT_RATE).fillna(HEAT_RATE['unknown'])
    df['vom']        = df['carrier'].map(VOM_ADDER).fillna(VOM_ADDER['unknown'])

    # marginal cost = fuel cost + VOM = (fuel price * heat rate) + VOM
    df['marginal_cost'] = (
        df['fuel_price'] * df['heat_rate'] + df['vom']
    ).round(2)

    return df[['bus', 'carrier', 'p_nom', 'marginal_cost']]


if __name__ == '__main__':
    n = pypsa.Network(NETWORK_PATH)
    result = compute_marginal_costs(n)

    print(result.groupby('carrier')['marginal_cost'].describe().round(2))
    print(f"\nMarginal cost range: ${result['marginal_cost'].min()} - ${result['marginal_cost'].max()}/MWh")

    result.to_csv(OUTPUT_PATH)
    print(f"Saved to {OUTPUT_PATH}")
