# "Bus Matching" Process

1. `extract_latlng_fuel.py`: .AUX file supporting grid
2. `build_network.py`: Texas2k series gives tentative synthetic grid, enriched with latlng fuel
3. `extract_eia860.py`: Extract EIA 860 lat/lng, fuel types
4. `match_generators.py`: Match EIA with Texas2k data set via proximity, fuel type

# Data

* [texas2k-series25](https://electricgrids.engr.tamu.edu/texas2k-series25/)
  * `Texas2k_series25_case1_summerpeak.m`: TAMU grid Matpower format
  * `Texas2k_series25_case1_summerpeak.AUX`: extract missing data (lat/lng) to add to network
    * Lat, Lng
    * Fuel Type
    * Unit Type

* [EIA-860](https://www.eia.gov/electricity/data/eia860/)
  * https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip
  * https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602023.zip
  * https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602022.zip

