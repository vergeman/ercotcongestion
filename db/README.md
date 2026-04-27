# Notes

* Run Migration:
  * `docker compose exec -T db psql -U <user> -d <db> < db/init/<migration>.sql`

## Import ERCOT

* Example single dataset:
  * `docker compose run --rm app python /data/ercot/backfill.py --start 2026-04-22 --end 2026-04-22 --endpoint loads`

* Remove all:
  * `docker compose exec db psql -U <user> -d <db> -c "DELETE FROM load_by_zone;"`

* Remove ingest_log to re-query (bad data):
  * `docker compose exec db psql -U <user> -d <db> -c "DELETE FROM ingest_log WHERE endpoint = 'loads';"`


## SQL Notes

### Data Types

* `TIMESTAMPTZ`: timestamp w/ time zone; stored in UTC, displayed in current
  session timezone.
  * ERCOT "default" for any timestamp, `sced_timestamp` `interval_ts`, etc
* `DOUBLE PRECISION`: 64bit float - corresponds to `float` in pandas.

* `INSERT INTO ... ON CONFICT DO UPDATE SET ... EXCLUDED.<fieldname>`: upsert
  behavior; `EXCLUDED` is a temporary table of new data - these are the fields
  being updated.
* `INSERT INTO ... ON CONFICT DO NOTHING`: silent skip - immutable data

### Fields / Conventions

* `solar_hourly_regional`, `wind_hourly_regional`, `load_by_zone`:
  * Query by (`interval_ts`, `dst_flag`)
  * NB: `PRIMARY KEY (interval_ts, dst_flag)`
  * See [daylight savings notes](/data/README.md#ERCOT Data)
