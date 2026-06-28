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
# Why port-forward instead of `kubectl exec -i ... | ...`:
#   Long-running `kubectl exec` sessions die on big tables — the websocket
#   to the k3s API server gets reset (load-balancer idle timeout, etc.) and
#   COPY aborts with "unexpected EOF in COPY data" after tens of millions of
#   rows. `kubectl port-forward` is more tolerant of long streams because the
#   libpq connection over the forwarded TCP socket has its own keepalives and
#   isn't subject to the API server's exec-session limits.
#
# Env vars (defaults):
#   PROD_NS           ercotstress
#   PROD_USER         ercot
#   PROD_DB           ercot
#   LOCAL_DB          ercot
#   LOCAL_CTR         db
#   MIGRATIONS_DIR    db/migrations          (relative or absolute)
#   LOCAL_PORT        5433                   (host port for kubectl port-forward)
#   RESUME_FROM       <empty>                (table name; skip drop+migrate and
#                                             start streaming at this table)
#
# Requirements:
#   - docker (we run psql as a one-off container using the timescale image,
#     so no host psql install is needed)
#
# Caveats:
#   - WIPES local data, unless RESUME_FROM is set.
#   - Run from the repo root so MIGRATIONS_DIR resolves.
#
# Examples:
#   ./export_database.sh                          # full sync
#   RESUME_FROM=bus_snapshots ./export_database.sh  # pick up after a failure

set -euo pipefail

# ---- config -----------------------------------------------------------------
PROD_NS="${PROD_NS:-ercotstress}"
PROD_USER="${PROD_USER:-ercot}"
PROD_DB="${PROD_DB:-ercot}"

LOCAL_CTR="${LOCAL_CTR:-db}"
LOCAL_DB="${LOCAL_DB:-ercot}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-db/migrations}"

LOCAL_PORT="${LOCAL_PORT:-5433}"
RESUME_FROM="${RESUME_FROM:-}"

# Tables to copy. Order matters only if you have FK constraints between them
# (you don't), but matching the order tables appear in migrations keeps things
# tidy. If you add a table to migrations, add it here too.
TABLES=(
  shadow_prices
  outages_zonal
  ingest_log
  load_by_zone
  wind_hourly_regional
  solar_hourly_regional
  bus_snapshots
  snapshot_meta
  ercot_zonal_lmp
  bus_load_zones
  ercot_dam_spp
  dam_system_lambda
  ercot_rt_lmp
  sced_system_lambda
  load_forecast_zonal
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

PSQL_IMAGE="${PSQL_IMAGE:-timescale/timescaledb:latest-pg16}"
if ! docker image inspect "$PSQL_IMAGE" >/dev/null 2>&1; then
  echo "ERROR: docker image '$PSQL_IMAGE' not found locally."
  echo "       docker pull $PSQL_IMAGE"
  exit 1
fi

PROD_PW="$(kubectl -n "$PROD_NS" exec "$PROD_POD" -- printenv POSTGRES_PASSWORD | tr -d '\r\n')"
if [[ -z "$PROD_PW" ]]; then
  echo "ERROR: could not read POSTGRES_PASSWORD from prod pod env."
  exit 1
fi

# Run psql against the port-forwarded prod DB via a one-off docker container.
# --network=host so we can reach the forward on localhost:$LOCAL_PORT (Linux).
# -i so stdin works for the COPY pipe; no -t (we're not on a TTY).
prod_psql() {
  docker run --rm -i --network=host \
    --entrypoint psql \
    -e PGPASSWORD="$PROD_PW" \
    "$PSQL_IMAGE" \
    -h localhost -p "$LOCAL_PORT" \
    -U "$PROD_USER" -d "$PROD_DB" \
    -v ON_ERROR_STOP=1 "$@"
}

if [[ -n "$RESUME_FROM" ]]; then
  # Validate the resume target is in TABLES, otherwise we'd skip everything.
  if ! printf '%s\n' "${TABLES[@]}" | grep -qx "$RESUME_FROM"; then
    echo "ERROR: RESUME_FROM='$RESUME_FROM' is not in the TABLES list."
    exit 1
  fi
  echo "    resume mode     : starting at '$RESUME_FROM' (skipping drop + migrations)"
fi

# ---- 1. terminate connections + drop/recreate target DB --------------------
if [[ -z "$RESUME_FROM" ]]; then
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
fi  # end RESUME_FROM guard

# ---- 3. start kubectl port-forward to prod postgres ------------------------
echo "==> Starting kubectl port-forward to prod postgres (localhost:$LOCAL_PORT)"
kubectl -n "$PROD_NS" port-forward "pod/$PROD_POD" "$LOCAL_PORT:5432" \
  >/tmp/export_db_pf.log 2>&1 &
PF_PID=$!
# Tear it down on any exit (success, error, Ctrl-C).
trap 'kill $PF_PID 2>/dev/null || true' EXIT INT TERM

# Wait up to 30s for the forward to accept connections.
for i in $(seq 1 30); do
  if prod_psql -c 'SELECT 1' >/dev/null 2>&1; then
    echo "    port-forward ready (pid=$PF_PID)"
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "ERROR: port-forward never became ready. See /tmp/export_db_pf.log"
    exit 1
  fi
  sleep 1
done

# ---- 4. stream each table from prod (via port-forward) to local -----------
echo "==> Streaming table data from prod to local"
SKIP=0
if [[ -n "$RESUME_FROM" ]]; then SKIP=1; fi
for tbl in "${TABLES[@]}"; do
  if [[ $SKIP -eq 1 ]]; then
    if [[ "$tbl" == "$RESUME_FROM" ]]; then
      SKIP=0
    else
      echo "    -- $tbl (skipped, already done)"
      continue
    fi
  fi
  echo "    -> $tbl"
  # Source: prod_psql (docker one-off, --network=host) -> port-forward -> prod pod.
  # Sink:   docker compose exec -> local postgres in the db container.
  # libpq's TCP keepalive on the source side keeps long streams alive much
  # better than `kubectl exec -i`'s websocket did.
  prod_psql -c "COPY (SELECT * FROM $tbl) TO STDOUT WITH (FORMAT BINARY)" \
  | docker compose exec -T "$LOCAL_CTR" \
      psql -U "$LOCAL_USER" -d "$LOCAL_DB" -v ON_ERROR_STOP=1 -c \
      "COPY $tbl FROM STDIN WITH (FORMAT BINARY)"
done

# ---- 5. verify --------------------------------------------------------------
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
SELECT 'shadow_prices'         AS tbl, count(*) FROM shadow_prices
UNION ALL SELECT 'outages_zonal',         count(*) FROM outages_zonal
UNION ALL SELECT 'ingest_log',            count(*) FROM ingest_log
UNION ALL SELECT 'load_by_zone',          count(*) FROM load_by_zone
UNION ALL SELECT 'wind_hourly_regional',  count(*) FROM wind_hourly_regional
UNION ALL SELECT 'solar_hourly_regional', count(*) FROM solar_hourly_regional
UNION ALL SELECT 'bus_snapshots',         count(*) FROM bus_snapshots
UNION ALL SELECT 'snapshot_meta',         count(*) FROM snapshot_meta
UNION ALL SELECT 'ercot_zonal_lmp',       count(*) FROM ercot_zonal_lmp
UNION ALL SELECT 'bus_load_zones',        count(*) FROM bus_load_zones
UNION ALL SELECT 'ercot_dam_spp',         count(*) FROM ercot_dam_spp
UNION ALL SELECT 'dam_system_lambda',     count(*) FROM dam_system_lambda
UNION ALL SELECT 'ercot_rt_lmp',          count(*) FROM ercot_rt_lmp
UNION ALL SELECT 'sced_system_lambda',    count(*) FROM sced_system_lambda
UNION ALL SELECT 'load_forecast_zonal',   count(*) FROM load_forecast_zonal
ORDER BY tbl;
SQL

echo
echo "==> Done."
echo "    Compare row counts above to prod. They should match."
