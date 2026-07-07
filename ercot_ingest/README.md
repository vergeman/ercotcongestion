# ERCOT Data

* API: https://developer.ercot.com/applications/pubapi/relnotes/
* NP4-191-CD — DAM Binding/Active Constraint Shadow Prices
  * https://www.ercot.com/mp/data-products/data-product-details?id=NP4-191-CD
  * API DAM Shadow Prices (hourly): /np4-191-cd/dam_shadow_prices

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

* Frequency of update

| product               | id         | frequency Update |
|-----------------------|------------|------------------|
| rt_lmp                | np6-788-cd | 5 min            |
| dam_spp               | np4-190-cd | 1 day            |
| dam_lambda            | np4-523-cd | 1 day            |
| sced lambda           | np6-322-cd | 5 min            |
| load_forecast         |            | hourly           |
| wind/solar            |            | hourly           |
| outage                |            | hourly           |
| dam_shadow            | np4-191-cd | 1 day            |
| actual_load           |            | daily            |
| spp zonal (lmp zonal) | np6-905-cd | 15 min           |


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
| DAM Shadow Prices  | No (one publish per DAM)  | Upsert (numerics)             |
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

### Cloudflare Proxy

* Deployed using `ercot-proxy` container - see `ercot_ingest/proxy/setup.sh`
* uploads `worker.js`

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
