#!/usr/bin/env bash
#
# Restore a backup produced by db/backup_prod.sh into a local docker-compose
# Postgres or a k3s pod.
#
# Prompts for the archive, the target, and the destination database name, then
# runs the only restore sequence that actually works for TimescaleDB:
#
#   CREATE EXTENSION timescaledb VERSION '<exact source version>'
#   SELECT timescaledb_pre_restore()      -- separate session: sets a DB-level GUC
#   pg_restore                            -- SEQUENTIAL, see below
#   SELECT timescaledb_post_restore()
#
# NEVER pass -j to pg_restore here. Parallel restore reorders the data loads,
# and _timescaledb_catalog has circular foreign keys between `chunk` and
# `chunk_constraint`. The FK fails, pg_restore prints "errors ignored on
# restore" and *exits 0*, and you get a database whose hypertables have zero
# chunks and zero rows while every plain table looks perfect. Verified
# 2026-08-19: -j 4 restored 0 of 43,201 rows; sequential restored all of them
# with an identical content md5. This script greps for that warning and fails.
#
# The extension version must match the source exactly. The timescale images
# ship dozens of versions, so a "newer" image is usually fine — you just have
# to pin the version at CREATE EXTENSION instead of taking the default.
#
# Env vars (all optional — they pre-seed the prompts):
#   BACKUP_FILE     <newest *.dump in ./db/backups>
#   TARGET          docker | k8s        (default docker)
#   DOCKER_SVC      db                  (compose service, when TARGET=docker)
#   TGT_NS          ercotstress         (namespace, when TARGET=k8s)
#   TGT_DB          <source_db>_restored
#   DROP_EXISTING   0                   (1 = drop the target DB without asking)
#   FORCE           0                   (1 = proceed despite version mismatch)
#
# Usage:
#   ./db/restore_backup.sh
#   TGT_DB=ercot DROP_EXISTING=1 ./db/restore_backup.sh < /dev/null

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./db/backups}"
DROP_EXISTING="${DROP_EXISTING:-0}"
FORCE="${FORCE:-0}"

ask() {
  local __ref="$1" label="$2" def="$3" ans
  if [[ ! -t 0 ]]; then
    printf -v "$__ref" '%s' "$def"
    echo "    $label: $def (non-interactive)"
    return
  fi
  read -r -p "    $label [$def]: " ans
  printf -v "$__ref" '%s' "${ans:-$def}"
}

die() { echo "ERROR: $*" >&2; exit 1; }

# ---- 1. pick the archive ----------------------------------------------------
echo "==> Archive"
NEWEST="$(ls -t "$BACKUP_DIR"/*.dump 2>/dev/null | head -1 || true)"
[[ -n "$NEWEST" ]] || die "no *.dump found in $BACKUP_DIR"
if [[ -t 0 ]]; then
  echo "    available:"
  ls -lht "$BACKUP_DIR"/*.dump | awk '{print "      " $9 "  " $5}'
fi
ask BACKUP_FILE "archive" "${BACKUP_FILE:-$NEWEST}"
[[ -f "$BACKUP_FILE" ]] || die "no such file: $BACKUP_FILE"

# ---- 2. read the sidecar metadata ------------------------------------------
META="${BACKUP_FILE%.dump}.meta"
SRC_DB=""; SRC_TS=""; SRC_PG=""; SRC_CHUNKS=""; SRC_TABLES=""
if [[ -f "$META" ]]; then
  # shellcheck disable=SC1090
  while IFS='=' read -r k v; do
    case "$k" in
      source_database) SRC_DB="$v" ;;
      timescaledb_version) SRC_TS="$v" ;;
      postgres_version) SRC_PG="$v" ;;
      chunks) SRC_CHUNKS="$v" ;;
      public_tables) SRC_TABLES="$v" ;;
    esac
  done < "$META"
  echo "    metadata: $SRC_DB @ PostgreSQL $SRC_PG / TimescaleDB $SRC_TS"
  echo "              $SRC_TABLES public tables, $SRC_CHUNKS chunks"
else
  echo "    WARNING: no .meta sidecar next to this archive."
  echo "             Version pinning and post-restore count checks are disabled."
fi

# Checksum, if we have one — a truncated archive restores "successfully".
if [[ -f "$BACKUP_FILE.sha256" ]]; then
  echo -n "    verifying checksum... "
  ( cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE").sha256" >/dev/null ) \
    || die "checksum mismatch — the archive is corrupt or incomplete"
  echo "ok"
fi

# ---- 3. pick the target -----------------------------------------------------
echo "==> Target"
ask TARGET "target (docker|k8s)" "${TARGET:-docker}"
case "$TARGET" in
  docker)
    ask DOCKER_SVC "compose service" "${DOCKER_SVC:-db}"
    docker compose ps --services --filter status=running | grep -qx "$DOCKER_SVC" \
      || die "compose service '$DOCKER_SVC' is not running (docker compose up -d $DOCKER_SVC)"
    tsh()    { docker compose exec -T "$DOCKER_SVC" sh -c "$1"; }
    tsh_in() { docker compose exec -T "$DOCKER_SVC" sh -c "$1"; }
    TARGET_DESC="docker compose service '$DOCKER_SVC'"
    ;;
  k8s)
    export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config-production-green.yml}"
    ask TGT_NS "namespace" "${TGT_NS:-ercotstress}"
    kubectl get ns "$TGT_NS" >/dev/null 2>&1 || die "no namespace '$TGT_NS'"
    TGT_POD="$(kubectl -n "$TGT_NS" get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    [[ -n "$TGT_POD" ]] || die "no pod labelled app=postgres in '$TGT_NS'"
    tsh()    { kubectl -n "$TGT_NS" exec "$TGT_POD" -- sh -c "$1"; }
    tsh_in() { kubectl -n "$TGT_NS" exec -i "$TGT_POD" -- sh -c "$1"; }
    TARGET_DESC="k8s $TGT_NS/$TGT_POD"
    echo "    !! this writes to a CLUSTER, not your laptop !!"
    ;;
  *) die "TARGET must be 'docker' or 'k8s' (got '$TARGET')" ;;
esac

# ---- 4. compatibility checks ------------------------------------------------
TGT_PG=$(tsh 'psql -U "$POSTGRES_USER" -d postgres -Atc "show server_version"' | tr -d '\r')
echo "    server: PostgreSQL $TGT_PG"

if [[ -n "$SRC_PG" ]]; then
  [[ "${SRC_PG%%.*}" == "${TGT_PG%%.*}" ]] \
    || die "PostgreSQL major version mismatch: dump is $SRC_PG, target is $TGT_PG"
fi

# The exact source extension version has to be installable here. The timescale
# images carry many versions, so this usually passes even on a newer image.
if [[ -n "$SRC_TS" ]]; then
  if tsh "psql -U \"\$POSTGRES_USER\" -d postgres -Atc \"select 1 from pg_available_extension_versions where name='timescaledb' and version='$SRC_TS'\"" 2>/dev/null | grep -q '^1$'; then
    echo "    timescaledb $SRC_TS is installable here"
  else
    echo "    timescaledb $SRC_TS is NOT available in this image. Available:"
    tsh "psql -U \"\$POSTGRES_USER\" -d postgres -Atc \"select version from pg_available_extension_versions where name='timescaledb'\"" 2>/dev/null | tr '\n' ' ' | sed 's|^|      |'
    echo
    [[ "$FORCE" == "1" ]] || die "use an image that ships $SRC_TS, or set FORCE=1 to restore at the default version"
  fi
fi

# ---- 5. destination database ------------------------------------------------
ask TGT_DB "restore into database" "${TGT_DB:-${SRC_DB:-restored}_restored}"

EXISTS=$(tsh "psql -U \"\$POSTGRES_USER\" -d postgres -Atc \"select 1 from pg_database where datname='$TGT_DB'\"" 2>/dev/null | tr -d '\r')
if [[ "$EXISTS" == "1" ]]; then
  SZ=$(tsh "psql -U \"\$POSTGRES_USER\" -d postgres -Atc \"select pg_size_pretty(pg_database_size('$TGT_DB'))\"" | tr -d '\r')
  echo
  echo "    !! database '$TGT_DB' already exists on $TARGET_DESC ($SZ) and will be DROPPED !!"
  if [[ "$DROP_EXISTING" != "1" ]]; then
    [[ -t 0 ]] || die "'$TGT_DB' exists; set DROP_EXISTING=1 to replace it non-interactively"
    read -r -p "    Type the database name to confirm: " confirm
    [[ "$confirm" == "$TGT_DB" ]] || { echo "aborted"; exit 1; }
  fi
fi

echo
echo "    archive  : $BACKUP_FILE"
echo "    target   : $TARGET_DESC"
echo "    database : $TGT_DB"
echo "    extension: timescaledb ${SRC_TS:-<default>}"
if [[ -t 0 ]]; then
  read -r -p "    Proceed? [Y/n]: " go
  [[ -z "${go:-}" || "$go" =~ ^[Yy] ]] || { echo "aborted"; exit 1; }
fi
echo

# ---- 6. restore -------------------------------------------------------------
echo "==> Recreating '$TGT_DB'"
tsh "psql -U \"\$POSTGRES_USER\" -d postgres -q -v ON_ERROR_STOP=1 \
  -c \"select pg_terminate_backend(pid) from pg_stat_activity where datname='$TGT_DB' and pid <> pg_backend_pid()\" \
  -c \"drop database if exists $TGT_DB\" \
  -c \"create database $TGT_DB\"" >/dev/null

EXT_CLAUSE="CREATE EXTENSION IF NOT EXISTS timescaledb"
[[ -n "$SRC_TS" ]] && EXT_CLAUSE="$EXT_CLAUSE VERSION '$SRC_TS'"
echo "==> $EXT_CLAUSE"
tsh "psql -U \"\$POSTGRES_USER\" -d $TGT_DB -q -v ON_ERROR_STOP=1 -c \"$EXT_CLAUSE\"" >/dev/null

# Own session: pre_restore sets a database-level GUC that only new connections see.
echo "==> timescaledb_pre_restore()"
tsh "psql -U \"\$POSTGRES_USER\" -d $TGT_DB -q -Atc 'select timescaledb_pre_restore()'" >/dev/null

echo "==> pg_restore (sequential — no -j, deliberately)"
RESTORE_LOG=$(mktemp)
set +e
tsh_in "pg_restore -U \"\$POSTGRES_USER\" -d $TGT_DB --no-owner --no-privileges" \
  < "$BACKUP_FILE" > "$RESTORE_LOG" 2>&1
RC=$?
set -e
tail -20 "$RESTORE_LOG" | sed 's|^|    |'

echo "==> timescaledb_post_restore()"
tsh "psql -U \"\$POSTGRES_USER\" -d $TGT_DB -q -Atc 'select timescaledb_post_restore()'" >/dev/null

# pg_restore exits 0 even when it skipped rows. The warning line is the truth.
if grep -q "errors ignored on restore" "$RESTORE_LOG"; then
  echo
  echo "ERROR: pg_restore reported ignored errors — this restore is NOT complete."
  grep -E "error|errors ignored" "$RESTORE_LOG" | head -20 | sed 's|^|    |'
  echo "    full log: $RESTORE_LOG"
  exit 1
fi
[[ $RC -eq 0 ]] || die "pg_restore exited $RC (log: $RESTORE_LOG)"
rm -f "$RESTORE_LOG"

echo "==> ANALYZE"
tsh "psql -U \"\$POSTGRES_USER\" -d $TGT_DB -q -c 'ANALYZE'" >/dev/null

# ---- 7. verify --------------------------------------------------------------
echo "==> Verifying"
GOT_CHUNKS=$(tsh "psql -U \"\$POSTGRES_USER\" -d $TGT_DB -Atc 'select count(*) from _timescaledb_catalog.chunk'" | tr -d '\r')
GOT_TABLES=$(tsh "psql -U \"\$POSTGRES_USER\" -d $TGT_DB -Atc \"select count(*) from pg_tables where schemaname='public'\"" | tr -d '\r')
echo "    chunks       : $GOT_CHUNKS${SRC_CHUNKS:+  (source: $SRC_CHUNKS)}"
echo "    public tables: $GOT_TABLES${SRC_TABLES:+  (source: $SRC_TABLES)}"

FAIL=0
[[ -n "$SRC_CHUNKS" && "$GOT_CHUNKS" != "$SRC_CHUNKS" ]] && { echo "    MISMATCH: chunk count"; FAIL=1; }
[[ -n "$SRC_TABLES" && "$GOT_TABLES" != "$SRC_TABLES" ]] && { echo "    MISMATCH: table count"; FAIL=1; }

echo "    hypertables:"
tsh "psql -U \"\$POSTGRES_USER\" -d $TGT_DB -c 'select hypertable_name, num_chunks from timescaledb_information.hypertables order by 1'" | sed 's|^|      |'

[[ $FAIL -eq 0 ]] || die "restore verification failed — do not trust this database"

echo
echo "==> Done. '$TGT_DB' restored on $TARGET_DESC."
[[ -f "${BACKUP_FILE%.dump}" ]] || true
echo "    Roles are not in this archive; on a fresh cluster load globals-*.sql separately."
