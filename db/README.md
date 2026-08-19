# Notes

* Run Migration:
  * `docker compose exec -T db psql -U <user> -d <db> < db/migrations/<migration>.sql`

* K3s migration:
  * `kubectl exec -i -n ercotstress postgres-0 -- psql -U <username> -d <db> < db/migrations/<migration>.sql`

## Import ERCOT

* Example single dataset:
  * `docker compose run --rm app python /data/ercot/backfill.py --start 2026-04-22 --end 2026-04-22 --endpoint loads`

* Remove all:
  * `docker compose exec db psql -U <user> -d <db> -c "DELETE FROM load_by_zone;"`

* Remove ingest_log to re-query (bad data):
  * `docker compose exec db psql -U <user> -d <db> -c "DELETE FROM ingest_log WHERE endpoint = 'loads';"`

## Scripts

* `./backup_prod.sh`: full one-shot backup of prod into `./db/backups/`. Use this
  for actual backups — see [Backup Prod](#backup-prod-one-shot-full).
* `./restore_backup.sh`: restore one of those archives into local docker or a
  k3s pod, with the version pinning and sequential-restore rules enforced.
* `./import_database.sh`: dump local into prod. Outdated, likely needs tables to
  be updated.

## Backup Prod (one-shot, full)

* TODO: restore on dev needs pinned version: `timescale/timescaledb:2.17.2-pg16`

`./db/backup_prod.sh` — takes a complete logical backup into `./db/backups/`.
Server-side compressed, pulled in resumable byte ranges, checksum-verified.

It prompts for the **namespace** and **database**, re-asking (and listing what
actually exists) until both resolve, then shows the pod, size, versions and node
disk headroom before doing anything. Env vars pre-seed the prompts; a
non-interactive stdin accepts the defaults without asking.

```
./db/backup_prod.sh                       # prompt, dump, pull, verify
PROD_NS=staging ./db/backup_prod.sh       # prompt pre-filled with 'staging'
STAMP=20260819-1313 ./db/backup_prod.sh   # resume an interrupted pull
./db/backup_prod.sh < /dev/null           # non-interactive, all defaults
```

Output:

| file | contents |
| --- | --- |
| `<db>-<stamp>.dump` | the whole database, `pg_dump -Fc -Z zstd:3` |
| `<db>-<stamp>.dump.sha256` | checksum, verified against the pod at pull time |
| `<db>-<stamp>.meta` | source versions + chunk/table counts, read back by the restore |
| `globals-<stamp>.sql` | roles and passwords (`pg_dumpall --globals-only`) |

The `.meta` sidecar is what lets a restore refuse a mismatched target and check
its own results, so a silent partial restore cannot pass unnoticed.

### pg_dump and hypertables — the two real traps

pg_dump does **not** silently drop hypertable data. Two separate things bite:

1. **Filtering the dump.** A hypertable's parent owns no rows; every row lives in
   a chunk under `_timescaledb_internal`. So `pg_dump --table=public.load_by_zone`
   yields an empty table, and `--schema=public` drops all 1200+ chunks. Never pass
   `-t`/`-n`/`-T`/`-N`. Dump the whole database.
2. **Restoring naively.** An unfiltered dump *does* contain every chunk, but they
   come back as `CREATE TABLE` statements that Timescale's DDL hooks reject or
   mangle. The fix is `timescaledb_pre_restore()` / `timescaledb_post_restore()`
   (below) — not abandoning pg_dump.

The removed `export_prod_database.sh` worked around (2) by streaming `COPY`
through a hand-maintained `TABLES` array. That was slow, and the array rotted: as
of 2026-08-19 prod had 28 public tables and the array listed 17, so
`forecast_nodal`, `forecast_sf_artifact`, `constraint_geo`, `resource_outages`,
the scoreboards and 8 others were absent from any "backup" it produced. It is
kept in git history only; use `backup_prod.sh`.

### Restore a backup

```
./db/restore_backup.sh
```

Prompts for the archive (defaults to the newest), the target (`docker` compose
service or a `k8s` namespace/pod), and the destination database. Before writing
anything it verifies the sha256, refuses a PostgreSQL major-version mismatch,
and confirms the source's exact TimescaleDB version is installable on the
target. If the destination database already exists you must type its name to
confirm the drop. Afterwards it compares the restored chunk and table counts
against the `.meta` sidecar and fails if they disagree.

```
./db/restore_backup.sh                                        # interactive
TGT_DB=ercot DROP_EXISTING=1 ./db/restore_backup.sh < /dev/null
TARGET=k8s TGT_NS=ercotstress ./db/restore_backup.sh          # writes to a CLUSTER
```

#### Extension versions

The target needs the **same PostgreSQL major version** and the **same
TimescaleDB version the dump came from** — but that rarely means a different
image. The `timescale/timescaledb` images ship dozens of extension versions
alongside the default: `latest-pg16` (default 2.26.3) also carries prod's
2.17.2. So restoring a prod dump into local dev works, provided you pin the
version at `CREATE EXTENSION` rather than accepting the default. The script does
this for you from the `.meta` file.

Check what a given image offers:

```
SELECT version FROM pg_available_extension_versions WHERE name = 'timescaledb';
```

#### Doing it by hand

```
# 1. fresh database with the extension pinned to the SOURCE's version
psql -U ercot -d postgres -c "CREATE DATABASE ercot_restored OWNER ercot;"
psql -U ercot -d ercot_restored -c "CREATE EXTENSION IF NOT EXISTS timescaledb VERSION '2.17.2';"

# 2. put Timescale in restoring mode. Must be its own psql session: this sets a
#    database-level GUC that only new connections pick up.
psql -U ercot -d ercot_restored -c "SELECT timescaledb_pre_restore();"

# 3. restore. Single-threaded — NO -j (see below). No --clean, no -C, no -t/-n.
pg_restore -U ercot -d ercot_restored --no-owner --no-privileges db/backups/ercot-<stamp>.dump

# 4. rebuild Timescale's internal state (catalog sequences, jobs, caches)
psql -U ercot -d ercot_restored -c "SELECT timescaledb_post_restore();"
psql -U ercot -d ercot_restored -c "ANALYZE;"
```

**Never pass `-j` to `pg_restore` here.** Parallel restore reorders the data
loads, and `_timescaledb_catalog` has circular foreign keys between `chunk` and
`chunk_constraint`. The FK fails, pg_restore reports `errors ignored on restore`
and *exits 0*, and you are left with a database whose hypertables have zero
chunks and zero rows — while every plain table restored fine. Verified
2026-08-19 on a 43,201-row hypertable: `-j 4` gave 0 rows / 0 chunks; the same
archive restored sequentially gave 43,201 rows / 31 chunks with an md5 of the
row contents identical to the source. This is the most likely explanation for
past restores that appeared to "miss entire tables".

Always read pg_restore's output. `errors ignored on restore: N` means the
restore is bad, regardless of the exit code.

Roles are not in the dump — on a brand-new cluster load them first:
`psql -U postgres -f db/backups/globals-<stamp>.sql`.

Sanity check after restore — chunk count must match the source, and a fresh
insert must route into a new chunk (proves the hypertable is live, not a bare
table):

```
SELECT count(*) FROM _timescaledb_catalog.chunk;                -- vs .meta
SELECT hypertable_name, num_chunks FROM timescaledb_information.hypertables ORDER BY 1;
```

## Backup Docker Volume (Local)

```
docker compose stop db

docker run --rm \
  -v ercotstress_pgdata:/src \
  -v "$PWD":/backup \
  alpine \
  tar czf /backup/pgdata-$(date +%Y%m%d-%H%M).tar.gz -C /src .

docker compose start db
```

## Restore Docker Volume (Local)

```
docker compose down             # stops db and removes container
docker volume rm ercotstress_pgdata
docker volume create ercotstress_pgdata
docker run --rm \
  -v ercotstress_pgdata:/dst \
  -v "$PWD":/backup \
  alpine \
  tar xzf /backup/pgdata-YYYYMMDD-HHMM.tar.gz -C /dst
docker compose up -d db
```

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

### Tables / Fields / Conventions

* `solar_hourly_regional`, `wind_hourly_regional`, `load_by_zone`:
  * Query by (`interval_ts`, `dst_flag`)
  * NB: `PRIMARY KEY (interval_ts, dst_flag)`
  * See [daylight savings notes](/data/README.md#ERCOT Data)
