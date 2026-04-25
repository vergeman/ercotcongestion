# "Bus Matching" Process

1. `extract_latlng_fuel.py`: .AUX file supporting grid
2. `build_network.py`: Texas2k series gives tentative synthetic grid, enriched with latlng fuel
3. `extract_eia860.py`: Extract EIA 860 lat/lng, fuel types
4. `match_generators.py`: Match EIA with Texas2k data set via proximity, fuel type
5. `assign_zones.py`: Given TAMU network Bus lat/lng, assign zone label
6. `marginal_costs.py`: generates marginal_costs.csv for plant types (hardcoded
    table lookups; so not plan specific for now)

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

* [Zone Data Shapefiles](https://figshare.com/ndownloader/files/39478540)
  * Shapefiles that provide polygons for the 8 ERCOT zones.
  * `/data/ercot_zones/Weather_Zone.*`*

* ERCOT Data
  * API: https://developer.ercot.com/applications/pubapi/relnotes/
  * NP6-86-CD — SCED Shadow Prices and Binding Transmission Constraints
    * https://www.ercot.com/mp/data-products/data-product-details?id=NP6-86-CD
    * API Shadow Prices 5-min Increments: /np6-86-cd/shdw_prices_bnd_trns_const
  * NP3-233-CD — Hourly Resource Outage Capacity
    * https://www.ercot.com/mp/data-products/data-product-details?id=NP3-233-CD
    * API Outage Info: /np3-233-cd/hourly_res_outage_cap

  * Zone Loads 15min
    * API: /np6-345-cd/act_sys_load_by_wzn

  * Wind hourly
    * API: actual+forecast/np4-732-cd/wpp_hrly_avrg_actl_fcast

  * Solar actual + forecast (hourly)
    * API: /np4-737-cd/spp_hrly_avrg_actl_fcast
      * np4-745-cd is by geographical region - not sure

  * Daylight Saving Time
    * `dst_flag`: ERCOT publishes CST; publishes `dst_flag` True on "second" instance of time.
    * `repeated_hour_flag`: same for shadow prices
    * `interval_ts`: calculates UTC using the flag

  * `docker compose run --rm app python /data/ercot/backfill.py \
     --start 2026-02-23 --end 2026-04-23 --resume`
