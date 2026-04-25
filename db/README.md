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
