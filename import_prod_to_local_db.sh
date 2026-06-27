#!/usr/bin/env bash
#
# Sync prod k3s Postgres data down into local docker-compose.
#
# Pipeline:
#   1. Drop and recreate the local database (empty)
#   2. Run db/migrations/*.sql in order against the new empty DB
#   3. Stream each table's data from prod to local via COPY
#
# Why streamed COPY instead of pg_dump | pg_restore:
#   pg_dump treats a Timescale hypertable's parent as a regular table with no
#   data of its own (because all rows live in chunks under
#   _timescaledb_internal). With --table=public.X it dumps the parent and
#   produces zero rows; without --table it dumps each chunk by name, but
#   the destination chunks don't exist yet so the restore fails. Going
#   through the parent via COPY (SELECT * FROM tbl) TO STDOUT ... | COPY tbl
#   FROM STDIN reads from every chunk on the source side (Postgres inheritance
#   handles it transparently), and Timescale's chunk-routing trigger creates
#   chunks on the destination as rows arrive. Cleaner than fighting pg_dump's
#   hypertable handling, and bypasses the catalog-mismatch problem entirely.
#
# Env vars (defaults):
#   PROD_NS           ercotstress
#   PROD_USER         ercot
#   PROD_DB           ercot
#   LOCAL_DB          ercot
#   LOCAL_CTR         db
#   MIGRATIONS_DIR    db/migrations          (relative or absolute)
#
# Caveats:
#   - WIPES local data. Make sure you don't have local work you care about.
#   - Run from the repo root so MIGRATIONS_DIR resolves.

set -euo pipefail

# ---- config -----------------------------------------------------------------
PROD_NS="${PROD_NS:-ercotstress}"
PROD_USER="${PROD_USER:-ercot}"
PROD_DB="${PROD_DB:-ercot}"

LOCAL_CTR="${LOCAL_CTR:-db}"
LOCAL_DB="${LOCAL_DB:-ercot}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-db/migrations}"

# Tables to copy. Order matters only if you have FK constraints between them
# (you don't), but matching the order tables appear in migrations keeps things
# tidy. If you add a table to migrations, add it here too.
TABLES=(
  bus_load_zones
  ingest_log
  load_by_zone
  wind_hourly_regional
  solar_hourly_regional
  snapshot_meta
  ercot_zonal_lmp
  shadow_prices
  outages_zonal
  bus_snapshots
)

# ---- preflight --------------------------------------------------------------
echo "==> Preflight checks"

if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  echo "ERROR: migrations directory not found at '$MIGRATIONS_DIR'."
  echo "       Run from repo root, or set MIGRATIONS_DIR=/abs/path/to/db/migrations"
  exit 1
fi

MIGRATION_FILES=( "$MIGRATIONS_DIR"/*.sql )
if [[ ${#MIGRATION_FILES[@]} -eq 0 ]] || [[ ! -f "${MIGRATION_FILES[0]}" ]]; then
  echo "ERROR: no .sql files found under '$MIGRATIONS_DIR'"
  exit 1
fi
echo "    migrations dir  : $MIGRATIONS_DIR (${#MIGRATION_FILES[@]} files)"

if ! docker compose ps --services --filter status=running | grep -qx "$LOCAL_CTR"; then
  echo "ERROR: docker compose service '$LOCAL_CTR' is not running."
  echo "       Run: docker compose up -d $LOCAL_CTR"
  exit 1
fi

LOCAL_USER="$(docker compose exec -T "$LOCAL_CTR" sh -c 'echo "$POSTGRES_USER"' | tr -d '\r\n')"
if [[ -z "$LOCAL_USER" ]]; then
  echo "ERROR: could not read POSTGRES_USER from local container env."
  exit 1
fi
echo "    local container : $LOCAL_CTR (user=$LOCAL_USER, db=$LOCAL_DB)"
echo "    prod source     : $PROD_NS (user=$PROD_USER, db=$PROD_DB)"

PROD_POD="$(kubectl -n "$PROD_NS" get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}')"
if [[ -z "$PROD_POD" ]]; then
  echo "ERROR: no pod with label app=postgres in namespace $PROD_NS"
  exit 1
fi
echo "    prod pod        : $PROD_POD"

# ---- 1. terminate connections + drop/recreate target DB --------------------
echo "==> Terminating active connections and recreating local database"
docker compose exec -T "$LOCAL_CTR" \
  psql -U "$LOCAL_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$LOCAL_DB'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS $LOCAL_DB;
CREATE DATABASE $LOCAL_DB OWNER $LOCAL_USER;
SQL

# ---- 2. run migrations against the fresh local database --------------------
echo "==> Running migrations against fresh local database"
for f in $(printf '%s\n' "${MIGRATION_FILES[@]}" | sort); do
  fname="$(basename "$f")"
  echo "    -> $fname"
  # Pipe the file in from the host; no need to copy into the container.
  docker compose exec -T "$LOCAL_CTR" \
    psql -U "$LOCAL_USER" -d "$LOCAL_DB" -v ON_ERROR_STOP=1 -q < "$f"
done

# ---- 3. stream each table from prod to local -------------------------------
echo "==> Streaming table data from prod to local"
for tbl in "${TABLES[@]}"; do
  echo "    -> $tbl"
  # Stream binary COPY through stdin/stdout. -i on kubectl exec keeps stdin
  # attached on the prod (source) side; -T disables docker compose's TTY
  # allocation on the local (sink) side. Errors on either side surface
  # naturally because of `set -e` and the pipe.
  kubectl -n "$PROD_NS" exec -i "$PROD_POD" -- \
    psql -U "$PROD_USER" -d "$PROD_DB" -v ON_ERROR_STOP=1 -c \
    "COPY (SELECT * FROM $tbl) TO STDOUT WITH (FORMAT BINARY)" \
  | docker compose exec -T "$LOCAL_CTR" \
      psql -U "$LOCAL_USER" -d "$LOCAL_DB" -v ON_ERROR_STOP=1 -c \
      "COPY $tbl FROM STDIN WITH (FORMAT BINARY)"
done

# ---- 4. verify --------------------------------------------------------------
echo
echo "==> Verifying"
docker compose exec -T "$LOCAL_CTR" \
  psql -U "$LOCAL_USER" -d "$LOCAL_DB" <<'SQL'
\echo == Tables ==
\dt+

\echo
\echo == Hypertables and chunk counts ==
SELECT h.table_name AS hypertable,
       (SELECT count(*) FROM _timescaledb_catalog.chunk c
        WHERE c.hypertable_id = h.id) AS chunks
FROM _timescaledb_catalog.hypertable h
ORDER BY h.table_name;

\echo
\echo == Primary key check (one row per hypertable) ==
SELECT t.relname AS table_name, c.conname AS pkey
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN _timescaledb_catalog.hypertable h ON h.table_name = t.relname
WHERE n.nspname = 'public' AND c.contype = 'p'
ORDER BY t.relname;

\echo
\echo == Row counts ==
SELECT 'ercot_zonal_lmp' AS tbl, count(*) FROM ercot_zonal_lmp
UNION ALL SELECT 'load_by_zone',          count(*) FROM load_by_zone
UNION ALL SELECT 'shadow_prices',         count(*) FROM shadow_prices
UNION ALL SELECT 'outages_zonal',         count(*) FROM outages_zonal
UNION ALL SELECT 'wind_hourly_regional',  count(*) FROM wind_hourly_regional
UNION ALL SELECT 'solar_hourly_regional', count(*) FROM solar_hourly_regional
UNION ALL SELECT 'bus_snapshots',         count(*) FROM bus_snapshots
UNION ALL SELECT 'snapshot_meta',         count(*) FROM snapshot_meta
UNION ALL SELECT 'ingest_log',            count(*) FROM ingest_log
UNION ALL SELECT 'bus_load_zones',        count(*) FROM bus_load_zones
ORDER BY tbl;
SQL

echo
echo "==> Done."
echo "    Compare row counts above to prod. They should match."
