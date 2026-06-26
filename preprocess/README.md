# "Bus Matching" Process

1. `extract_latlng_fuel.py`: .AUX file supporting grid
   * bus_coords.csv
   * substations.csv
   * gen_fuels.csv

2. `build_network.py`: Texas2k series gives tentative synthetic grid, enriched
   with latlng fuel

3. `assign_bus_weather_load_zones.py`: Given TAMU network Bus lat/lng lookup and
   assign to each bus:
   * EROCT 8 Weather Zone labels: `ercot_weather_zone`
   * ERCOT 4 Load Zone labels: `ercot_load_zone`
   * writes to `bus_ercot_weather_load_zones.csv`

4. `extract_eia860.py`: Extract EIA 860 lat/lng, fuel types

5. `match_generators.py`: Match EIA with Texas2k data set via proximity, fuel
   type
   * Note: extracting eia860 attempts to match TAMU vs real generation 1-1.
   * Helps with human-readable display and real-world counterpart, but not exact

6. `enrich_generators.py`: augments `generator_matches.csv`
   * For each generator:
     * Adds TIGER county column via lat/lng lookup for each generator
     * Applies respective Load Zone label from bus applied
       `assign_bus_weather_load_zones.py`
     * For solar and wind generators, take TIGER county and apply `pv_region`
       and `wind_region`

7. `marginal_costs.py`: generates `marginal_costs.csv` for plant types
    (hardcoded table lookups; so not plan specific for now)

# Model Data

* `Texas2k_series25_case1_summerpeak/`: model data
  * [Source: texas2k-series25](https://electricgrids.engr.tamu.edu/texas2k-series25/)
    * Make sure the file is `Texas2k_series2025.zip` (5.7MB) updated for 2025,
      not earlier `ACTIVSg2000.zip` (120MB - contains powerworld binary).
  * `Texas2k_series25_case1_summerpeak.m`: TAMU grid Matpower format
  * `Texas2k_series25_case1_summerpeak.AUX`: extract missing data (lat/lng) to add to network
    * Lat, Lng
    * Fuel Type
    * Unit Type
  * `Expansion_Planning_Problem_Data/Candidates.csv`: used in
    `/compute/experiments/zonal_load` for far west load feasibility experiments


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

* `/ercot_geocode`: see `/data/raw/ercot_geocode/README.md` for details.
  * NP6-788-CD: `cdr.*.LMPSROSNODENP6788_*.csv`
  * NP4-160-SG:
    * `CCP_Resource_Names_06112026_122819.csv`
    * `Hub_Name_AND_DC_Ties_06112026_122819.csv`
    * `NOIE_Mapping_06112026_122819.csv`
    * `Resource_Node_to_Unit_06112026_122819.csv`
    * `Settlement_Points_06112026_122819.csv`
  * NP3-988-ER: `124...ResDMEList_25062026.csv`
  * Stand Alone Generation Resources

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
