# "Bus Matching" Process

1. `extract_latlng_fuel.py`: .AUX file supporting grid

2. `build_network.py`: Texas2k series gives tentative synthetic grid, enriched with latlng fuel

3. `extract_eia860.py`: Extract EIA 860 lat/lng, fuel types

4. `match_generators.py`: Match EIA with Texas2k data set via proximity, fuel type
   * Note: extracting eia860 attempts to match TAMU vs real generation 1-1.
   * Helps with human-readable display and real-world counterpart, but not exact

5. `enrich_generators.py`: augments `generator_matches.csv`
   * For each generator:
     * Adds TIGER county column via lat/lng lookup for each generator
     * Adds respective Load Zone label from geojson lookup
     * For solar and wind generators, take TIGER county and apply `pv_region` and `wind_region`

6. `assign_weather_zones.py`: Given TAMU network Bus lat/lng, assign EROCT 8 Weather Zone label

7. `marginal_costs.py`: generates `marginal_costs.csv` for plant types (hardcoded
    table lookups; so not plan specific for now)

# Model Data

* `Texas2k_series25_case1_summerpeak/`: model data
  * [Source: texas2k-series25](https://electricgrids.engr.tamu.edu/texas2k-series25/)
  * `Texas2k_series25_case1_summerpeak.m`: TAMU grid Matpower format
  * `Texas2k_series25_case1_summerpeak.AUX`: extract missing data (lat/lng) to add to network
    * Lat, Lng
    * Fuel Type
    * Unit Type

* `eia860/`: [EIA-860 Generator and Plant Info](https://www.eia.gov/electricity/data/eia860/)
  * https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip
  * https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602023.zip
  * https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602022.zip

# Geo Data

* `/ercot_weather_zones/`: Shapefiles that provide polygons for the 8 ERCOT zones.
  * [Download: ERCOT Weather Zone Data Shapefiles](https://figshare.com/ndownloader/files/39478540)

* `/ercot_load_zones/`: Load Zones GeoJSON
  * [Source Meta](https://services3.arcgis.com/fwwoCWVtaahwlvxO/arcgis/rest/services/ERCOT_Load_Zones/FeatureServer/)
  * [Download GeoJSON](https://services3.arcgis.com/fwwoCWVtaahwlvxO/arcgis/rest/services/ERCOT_Load_Zones/FeatureServer/7/query?where=1%3D1&outFields=*&f=geojson)

* `ercot_wind_solar_zones_counties/`:Wind Region and Solar Region to Texas
  County Mappings
  * [Download](https://www.ercot.com/files/docs/2024/05/31/Wind%20and%20Solar%20Regions%20to%20County%20Mapping.xlsx)

* `./TIGER`: TIGER Shapefiles to lookup lat/lng to County (more reliable than
  assignment from eia860 county level data)
  * [Download](https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip)


# ERCOT Data

* API: https://developer.ercot.com/applications/pubapi/relnotes/
* NP6-86-CD — SCED Shadow Prices and Binding Transmission Constraints
  * https://www.ercot.com/mp/data-products/data-product-details?id=NP6-86-CD
  * API Shadow Prices 5-min Increments: /np6-86-cd/shdw_prices_bnd_trns_const

* NP3-233-CD — Hourly Resource Outage Capacity
  * https://www.ercot.com/mp/data-products/data-product-details?id=NP3-233-CD
  * By Load Zone
  * API Outage Info: /np3-233-cd/hourly_res_outage_cap

* Zone Loads 15min win
  * By Weather Zone
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

* `docker compose run --rm updater`
