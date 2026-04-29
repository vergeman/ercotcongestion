# "Bus Matching" Process

1. `extract_latlng_fuel.py`: .AUX file supporting grid

2. `build_network.py`: Texas2k series gives tentative synthetic grid, enriched with latlng fuel

3. `extract_eia860.py`: Extract EIA 860 lat/lng, fuel types

4. `match_generators.py`: Match EIA with Texas2k data set via proximity, fuel type
   * Note: extracting eia860 attempts to match TAMU vs real generation 1-1.
   * Helps with human-readable display and real-world counterpart, but not exact

5. `assign_bus_weather_load_zones.py`: Given TAMU network Bus lat/lng lookup and
   assign to each bus:
   * EROCT 8 Weather Zone labels: `ercot_weather_zone`
     * ERCOT 4 Load Zone labels: `ercot_load_zone`

6. `enrich_generators.py`: augments `generator_matches.csv`
   * For each generator:
     * Adds TIGER county column via lat/lng lookup for each generator
     * Adds respective Load Zone label from geojson lookup
     * For solar and wind generators, take TIGER county and apply `pv_region` and `wind_region`


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

# Geo Data Sources

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

## Geo Lookups

* ERCOT Weather Zone: Shapefiles for lat/lng lookup to 8 Weather Zone labels:
  (Coast, East, Far West, North, North Central, South, South Central, West)
* TIGER: Shapefiles lat/lng to USA County
* ERCOT Load Zones: GeoJSON format (flattened Shapefile bundle) to lookup
  lat/lng to 4 Load Zones (Houston, North, South, West)

Use GeoPandas to load files. Each dataset needs to be a GeoDataFrame (`gdf`) and
GeoPands (`gpd` runs a spatial join):

* `gpd.sjoin(points, polygons, how='left', predicate='within')`:
  * lookup points in polygons
  * `how`:
    * `left` join: keep all rows from left even if no match in polygon (NaN)
    * `inner` silently drops no matches
  * `predicate`:
    * `within`: point fully inside polygon
    * `intersects`: touch/overlap ok
    * `contains`: inverse of `within`; in this case point can't contain a polygon.


# ERCOT Data

* API: https://developer.ercot.com/applications/pubapi/relnotes/
* NP6-86-CD — SCED Shadow Prices and Binding Transmission Constraints
  * https://www.ercot.com/mp/data-products/data-product-details?id=NP6-86-CD
  * API Shadow Prices 5-min Increments: /np6-86-cd/shdw_prices_bnd_trns_const

* NP3-233-CD — Hourly Resource Outage Capacity
  * https://www.ercot.com/mp/data-products/data-product-details?id=NP3-233-CD
  * By Load Zone
  * API Outage Info: /np3-233-cd/hourly_res_outage_cap
  * NB: includes scheduled future outages, hence dates extending into future

* Zonal LMP prices
  * By Load Zone
  * API: /np6-905-cd/spp_node_zone_hub

* Zone Loads 15min win
  * By Weather Zone
  * No forecasts
  * API: /np6-345-cd/act_sys_load_by_wzn

* Wind hourly:
  * API: /np4-742-cd/wpp_hrly_actual_fcast_geo
  * actual (gen_zone) + forecast if future

* Solar actual + forecast (hourly)
  * API: /np4-745-cd/spp_hrly_actual_fcast_geo
  * actual (gen_zone) + forecast if future

* Daylight Saving Time
  * `dst_flag`: ERCOT publishes CST; publishes `dst_flag` True on "second"
    instance of time.
  * `repeated_hour_flag`: same for shadow prices
  * `interval_ts`: calculates UTC using the flag

* `docker compose run --rm app python /data/ercot/backfill.py \
   --start 2026-02-23 --end 2026-04-23 --resume`

* `docker compose run --rm updater`

## ERCOT Data Updates

| Report             | Republish                 | Loader                        |
|--------------------|---------------------------|-------------------------------|
| Shadow Prices SCED | No (new pub every 5min)   | DO NOTHING                    |
| Load by Zone       | No                        | DO NOTHING                    |
| Outages Zonal      | Yes (revised outage list) | DO NOTHING - See Key*         |
| Wind Regional      | Yes (revised forecast)    | Upsert to most recent dataset |
| Solar Regional     | Yes (revised forecast)    | Upsert to most recent dataset |

* Zonal Outages: `(posted_datetime, operating_date, hour_ending)` - tuple key
  means new records will be inserted on new reports, if it's a newly specified
  outage; otherwise its a;ready known information.

## ERCOT API Access

* Geo-restricted, hence proxying via Cloudflare Worker (since not sure where
  hosting might be abroad aka Hetzner)

* `https://developer.ercot.com`: browse reports

### API URL Format

* Base URL: `https://api.ercot.com/api/public-reports/`

* Report Path appended: `np4-742-cd/wpp_hrly_actual_fcast_geo`
  * `np4`: "non-public" but often public
  * `742`: Report ID
  * `cd`: "Current Day"
  * `wpp_hrly..`: human readable dataset name

* Some reports require `{id}` parameter

* Query parameters:
  * Filter date range: `?deliveryDateFrom=xxx&deliveryDateTo=xxxx`
  * Pagination: API response has 1000 records per page limit.
  * add `page` param, `size`: (record num returned) - have to loop and increment
    page counter, while watching `totalPages` response.


### Quick Auth Flow

* See `/data/ercot/ErcotClient.py`:

  * Get API Credentials: username, password, subscription key_
  * Get Token: (username, password) + public `CLIENT_ID` with `response_type`
    `id_token`.
  * POST: `https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/B2C_1A_SIGNUPSIGNIN/oauth2/v2.0/token`
  * In report request headers, pass:

```json
{
  "Authorization: "Bearer {token}",
  "Ocp-Apim-Subscription-Key": {subscription_key},
}

```

