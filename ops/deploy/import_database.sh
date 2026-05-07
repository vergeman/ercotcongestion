#!/usr/bin/env bash
#
# Copy the local docker-compose Postgres DB into the prod k8s StatefulSet.
#
# Usage:
#   ./scripts/copy-db-to-prod.sh
#
# Requires:
#   - docker compose stack running locally with the `db` service up
#   - kubectl context pointing at the prod cluster
#
# Env vars (with defaults):
#   PROD_NS      ercotstress
#   PROD_SVC     postgres
#   PROD_USER    ercot
#   PROD_DB      ercot
#   LOCAL_DB     ercot
#   LOCAL_CTR    db                            (compose container_name)
#   DUMP_FILE    /tmp/ercot-local.dump
#
# What this script does:
#   1. Dumps the local DB to a custom-format file via `docker compose exec`
#   2. Copies the dump into the prod postgres pod
#   3. Terminates active connections to the prod DB
#   4. DROPs and recreates the prod database empty
#   5. pg_restore into the fresh DB (single-threaded; see note below)
#
# Why drop+recreate instead of timescaledb_pre_restore/post_restore:
#   pg_restore wants to CREATE EXTENSION timescaledb at the start of the
#   restore. If the extension is already loaded in the target DB (which it is,
#   because our k8s migrations created it), pg_restore fails with
#   "extension already loaded with another version" and aborts the entire
#   transaction. Dropping the database gives pg_restore a clean slate so the
#   CREATE EXTENSION succeeds and timescale chunks/hypertables restore
#   correctly.
#
# Why single-threaded restore (no --jobs):
#   With --jobs=N, pg_restore reorders work in parallel. TimescaleDB's chunk
#   creation triggers fire during data load and create indexes automatically;
#   meanwhile other workers try to CREATE INDEX from the dump's index step.
#   The race produces "relation already exists" errors AND, more dangerously,
#   chunks that lack dimension slices ("chunk _hyper_X_Y_chunk has no
#   dimension slices") — i.e. data is loaded but Timescale's catalog can't
#   route queries to it. Hypertables show 0 bytes despite having underlying
#   data. Single-threaded restore preserves dump ordering and avoids the race.
#   For a ~150MB dump this takes minutes, not seconds; acceptable tradeoff.
#
# Caveat: this WIPES prod data. The API will see connection errors briefly
# during step 4. Run when you're OK with that — typically before turning on
# the ingest CronJob.

set -euo pipefail

# ---- config -----------------------------------------------------------------
PROD_NS="${PROD_NS:-ercotstress}"
PROD_SVC="${PROD_SVC:-postgres}"
PROD_USER="${PROD_USER:-ercot}"
PROD_DB="${PROD_DB:-ercot}"

LOCAL_CTR="${LOCAL_CTR:-db}"
LOCAL_DB="${LOCAL_DB:-ercot}"
DUMP_FILE="${DUMP_FILE:-/tmp/ercot-local.dump}"

# ---- preflight --------------------------------------------------------------
echo "==> Preflight checks"

if ! docker compose ps --services --filter status=running | grep -qx "$LOCAL_CTR"; then
  echo "ERROR: docker compose service '$LOCAL_CTR' is not running."
  echo "       Run: docker compose up -d $LOCAL_CTR"
  exit 1
fi

# Look up the local Postgres user from inside the container so we don't have
# to source .env from the host.
LOCAL_USER="$(docker compose exec -T "$LOCAL_CTR" sh -c 'echo "$POSTGRES_USER"' | tr -d '\r\n')"
if [[ -z "$LOCAL_USER" ]]; then
  echo "ERROR: could not read POSTGRES_USER from the local container env."
  exit 1
fi
echo "    local container : $LOCAL_CTR (user=$LOCAL_USER, db=$LOCAL_DB)"
echo "    prod target     : $PROD_NS/$PROD_SVC (user=$PROD_USER, db=$PROD_DB)"

PROD_POD="$(kubectl -n "$PROD_NS" get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}')"
if [[ -z "$PROD_POD" ]]; then
  echo "ERROR: no pod found with label app=postgres in namespace $PROD_NS"
  exit 1
fi
echo "    prod pod        : $PROD_POD"

# ---- 1. dump ----------------------------------------------------------------
echo "==> Dumping local DB to $DUMP_FILE"
docker compose exec -T "$LOCAL_CTR" \
  pg_dump \
    --username="$LOCAL_USER" \
    --dbname="$LOCAL_DB" \
    --format=custom \
    --no-owner \
    --no-privileges \
  > "$DUMP_FILE"

DUMP_SIZE="$(du -h "$DUMP_FILE" | awk '{print $1}')"
echo "    wrote $DUMP_SIZE"

# ---- 2. copy dump into prod pod --------------------------------------------
echo "==> Copying dump into prod pod"
REMOTE_DUMP="/tmp/ercot-local.dump"
kubectl -n "$PROD_NS" cp "$DUMP_FILE" "$PROD_POD:$REMOTE_DUMP"

# ---- 3 + 4. terminate active connections + recreate target DB --------------
# Combine into one psql session: terminate other backends, then DROP/CREATE.
# Connect to the `postgres` meta-DB so we're not connected to the DB we're
# about to drop.
echo "==> Terminating active connections and recreating target database"
kubectl -n "$PROD_NS" exec -i "$PROD_POD" -- \
  psql -U "$PROD_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$PROD_DB'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS $PROD_DB;
CREATE DATABASE $PROD_DB OWNER $PROD_USER;
SQL

# ---- 5. restore (SINGLE-THREADED) ------------------------------------------
# No --jobs flag: required for TimescaleDB to avoid catalog corruption.
# No --clean --if-exists: DB is empty.
echo "==> Restoring into prod (single-threaded; this takes a few minutes)"
kubectl -n "$PROD_NS" exec "$PROD_POD" -- \
  pg_restore \
    --username="$PROD_USER" \
    --dbname="$PROD_DB" \
    --no-owner \
    --no-privileges \
    --verbose \
    "$REMOTE_DUMP" 2>&1 | tail -20 || {
      echo "WARNING: pg_restore exited non-zero. Some 'already exists' warnings"
      echo "         may be harmless, but verify hypertables below."
    }

# ---- 6. cleanup remote dump -------------------------------------------------
kubectl -n "$PROD_NS" exec "$PROD_POD" -- rm -f "$REMOTE_DUMP"

# ---- 7. verify hypertable health -------------------------------------------
# If chunks lost dimension slices during restore, queries against hypertables
# will fail. Check now while the script is still running.
echo
echo "==> Verifying hypertable integrity"
kubectl -n "$PROD_NS" exec -i "$PROD_POD" -- \
  psql -U "$PROD_USER" -d "$PROD_DB" <<'SQL'
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
\echo == Row counts (should match local DB) ==
SELECT 'ercot_zonal_lmp' AS tbl, count(*) FROM ercot_zonal_lmp
UNION ALL SELECT 'load_by_zone',     count(*) FROM load_by_zone
UNION ALL SELECT 'shadow_prices',    count(*) FROM shadow_prices
UNION ALL SELECT 'outages_zonal',    count(*) FROM outages_zonal
UNION ALL SELECT 'bus_snapshots',    count(*) FROM bus_snapshots
UNION ALL SELECT 'snapshot_meta',    count(*) FROM snapshot_meta;
SQL

echo
echo "==> Done."
echo "    If row counts above look right and no 'no dimension slices' errors"
echo "    appeared, the restore is clean."
echo
echo "    The API pod may have logged connection errors during the recreate."
echo "    Restart if it doesn't recover on its own:"
echo "      kubectl -n $PROD_NS rollout restart deployment/api"
