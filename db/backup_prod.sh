#!/usr/bin/env bash
#
# One-shot full logical backup of a k3s Postgres/TimescaleDB database.
#
# Prompts for the namespace and database, then produces in ./db/backups/:
#   <db>-<stamp>.dump          pg_dump custom format, zstd-compressed
#   <db>-<stamp>.dump.sha256   checksum, verified against the pod at pull time
#   <db>-<stamp>.meta          source versions + row/chunk counts (restore reads this)
#   globals-<stamp>.sql        roles and passwords (pg_dumpall --globals-only)
#
# Restore with db/restore_backup.sh.
#
# Why a plain full pg_dump works here, contrary to the old export_prod_database.sh:
#   pg_dump does NOT lose hypertable data. Rows live in chunks under
#   _timescaledb_internal, and an unfiltered pg_dump dumps every chunk by name
#   along with the _timescaledb_catalog that describes them. What breaks is
#   (a) filtering — `--table=public.X` dumps the hypertable parent, which owns
#   no rows, so you get an empty table; likewise `--schema=public` drops every
#   chunk on the floor. And (b) restoring naively — chunks arrive as CREATE
#   TABLE statements that Timescale's DDL hooks reject. The fix for (b) is
#   timescaledb_pre_restore()/timescaledb_post_restore(), not avoiding pg_dump.
#   So: never pass -t/-n/-T/-N here. Dump the whole database or nothing.
#
# Why not the streamed-COPY approach the old export_prod_database.sh used:
#   That walks a hand-maintained TABLES list one table at a time, single
#   threaded, decoding and re-encoding every row. It is slow, and the list
#   silently rots — any table added to migrations and not to the array is just
#   absent from the "backup". This script asks the server for everything.
#
# Why the dump is written inside the pod and then pulled:
#   Compressing server-side sends ~5x less over the wire, and a detached
#   (nohup) pg_dump survives the kubectl exec websocket dropping, which is what
#   killed the long streaming sessions before. The pull is done in byte ranges
#   via dd so an interrupted transfer resumes instead of restarting.
#
# Env vars (all optional — they pre-seed the prompts):
#   PROD_NS       ercotstress   (prompted)
#   PROD_DB       ercot         (prompted)
#   OUT_DIR       ./db/backups
#   BLOCK_MB      64            (pull chunk size)
#   KEEP_REMOTE   0             (1 = leave the dump on the pod's volume)
#   STAMP         <now>         (set it to resume an interrupted pull)
#
# Usage:
#   ./db/backup_prod.sh                        # prompt, dump, pull, verify
#   PROD_NS=staging ./db/backup_prod.sh        # prompt pre-filled with 'staging'
#   STAMP=20260819-1313 ./db/backup_prod.sh    # resume: reuse/pull an existing dump
#   ./db/backup_prod.sh < /dev/null            # non-interactive: accept all defaults

set -euo pipefail

# ---- config -----------------------------------------------------------------
# kubectl on this host has no usable default kubeconfig — it falls back to
# /etc/rancher/k3s/k3s.yaml, which isn't readable — so point at the prod file
# explicitly unless the caller already exported one.

OUT_DIR="${OUT_DIR:-./db/backups}"
BLOCK_MB="${BLOCK_MB:-64}"
KEEP_REMOTE="${KEEP_REMOTE:-0}"
REMOTE_DIR="/var/lib/postgresql/data/backup"   # on the PVC, survives pod restarts

# ---- prompts ----------------------------------------------------------------
# Interactive by default, so you have to actually look at which cluster and
# database you are about to read. A non-interactive stdin (cron, CI,
# `< /dev/null`) silently accepts the defaults so the script stays scriptable.
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

echo "==> Backup source"
echo "    kubeconfig: $KUBECONFIG"

# Namespace: re-ask until it resolves, showing what actually exists.
while :; do
  ask PROD_NS "namespace" "${PROD_NS:-ercotstress}"
  kubectl get ns "$PROD_NS" >/dev/null 2>&1 && break
  echo "    no namespace '$PROD_NS'. Available:"
  kubectl get ns -o name 2>/dev/null | sed 's|namespace/|      |' || {
    echo "      (cannot reach the cluster — check KUBECONFIG)"; exit 1; }
  [[ -t 0 ]] || exit 1
done

POD="$(kubectl -n "$PROD_NS" get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [[ -z "$POD" ]]; then
  echo "ERROR: no pod labelled app=postgres in namespace '$PROD_NS'. Pods there:"
  kubectl -n "$PROD_NS" get pods -o name 2>/dev/null | sed 's|^|      |'
  exit 1
fi

ksh() { kubectl -n "$PROD_NS" exec "$POD" -- sh -c "$1"; }

# Database: re-ask until it exists in that pod.
while :; do
  ask PROD_DB "database" "${PROD_DB:-ercot}"
  if ksh "psql -U \"\$POSTGRES_USER\" -d postgres -Atc \"select 1 from pg_database where datname='$PROD_DB'\"" 2>/dev/null | grep -q '^1$'; then
    break
  fi
  echo "    no database '$PROD_DB' in $POD. Available:"
  ksh "psql -U \"\$POSTGRES_USER\" -d postgres -c \"select datname, pg_size_pretty(pg_database_size(datname)) as size from pg_database where not datistemplate order by 1\"" 2>/dev/null | sed 's|^|      |'
  [[ -t 0 ]] || exit 1
done

STAMP="${STAMP:-$(date +%Y%m%d-%H%M)}"
DUMP="$PROD_DB-$STAMP.dump"
GLOBALS="globals-$STAMP.sql"
META="$PROD_DB-$STAMP.meta"

DB_SIZE=$(ksh "psql -U \"\$POSTGRES_USER\" -d postgres -Atc \"select pg_size_pretty(pg_database_size('$PROD_DB'))\"" | tr -d '\r')
PG_VER=$(ksh "psql -U \"\$POSTGRES_USER\" -d $PROD_DB -Atc 'show server_version'" | tr -d '\r')
TS_VER=$(ksh "psql -U \"\$POSTGRES_USER\" -d $PROD_DB -Atc \"select extversion from pg_extension where extname='timescaledb'\"" | tr -d '\r')

echo
echo "    namespace : $PROD_NS"
echo "    pod       : $POD"
echo "    database  : $PROD_DB ($DB_SIZE)"
echo "    versions  : PostgreSQL $PG_VER / TimescaleDB ${TS_VER:-<none>}"
echo "    output    : $OUT_DIR/$DUMP"
ksh "df -h /var/lib/postgresql/data | tail -1 | sed 's|^|    node disk : |'"
if [[ -t 0 ]]; then
  read -r -p "    Proceed? [Y/n]: " go
  [[ -z "${go:-}" || "$go" =~ ^[Yy] ]] || { echo "aborted"; exit 1; }
fi
echo

mkdir -p "$OUT_DIR"

# ---- 1. dump (detached, so a dropped exec session doesn't kill it) ----------
if ksh "test -f $REMOTE_DIR/$DUMP" 2>/dev/null; then
  echo "==> Remote dump $DUMP already exists, skipping pg_dump"
else
  echo "==> Starting detached pg_dump inside the pod"
  ksh "
    set -e
    mkdir -p $REMOTE_DIR && cd $REMOTE_DIR && rm -f dump.log
    nohup sh -c '
      pg_dump -U \"\$POSTGRES_USER\" -d $PROD_DB -Fc -Z zstd:3 -v -f $DUMP 2>>dump.log
      echo PG_DUMP_EXIT=\$? >> dump.log
      pg_dumpall -U \"\$POSTGRES_USER\" --globals-only -f $GLOBALS 2>>dump.log
      echo DONE >> dump.log
    ' >/dev/null 2>&1 &
  "
  echo "==> Waiting for dump to finish (polling every 30s)"
  while true; do
    if ksh "grep -q '^DONE' $REMOTE_DIR/dump.log 2>/dev/null" 2>/dev/null; then break; fi
    sz=$(ksh "du -h $REMOTE_DIR/$DUMP 2>/dev/null | cut -f1" 2>/dev/null || true)
    cur=$(ksh "tail -1 $REMOTE_DIR/dump.log 2>/dev/null" 2>/dev/null || true)
    echo "    ${sz:-?} written | ${cur:-...}"
    sleep 30
  done
  ksh "grep -E 'PG_DUMP_EXIT' $REMOTE_DIR/dump.log"
  if ! ksh "grep -q 'PG_DUMP_EXIT=0' $REMOTE_DIR/dump.log"; then
    echo "ERROR: pg_dump failed. Tail of log:"; ksh "tail -20 $REMOTE_DIR/dump.log"; exit 1
  fi
fi

# ---- 2. resumable pull ------------------------------------------------------
REMOTE_SIZE=$(ksh "stat -c %s $REMOTE_DIR/$DUMP" | tr -d '\r')
echo "==> Pulling $DUMP ($(numfmt --to=iec "$REMOTE_SIZE" 2>/dev/null || echo "$REMOTE_SIZE B"))"
LOCAL="$OUT_DIR/$DUMP"
BS=$((BLOCK_MB * 1024 * 1024))

while :; do
  have=$( [[ -f "$LOCAL" ]] && stat -c %s "$LOCAL" || echo 0 )
  (( have >= REMOTE_SIZE )) && break
  # Rewind to a whole-block boundary so a half-written block is refetched, not appended to.
  skip=$(( have / BS ))
  truncate -s $(( skip * BS )) "$LOCAL" 2>/dev/null || : > "$LOCAL"
  echo "    resuming at block $skip ($(( skip * BLOCK_MB )) MiB of $(( REMOTE_SIZE / BS + 1 )) blocks)"
  # No -t: kubectl exec keeps stdout binary-clean. Failure here just loops.
  kubectl -n "$PROD_NS" exec "$POD" -- \
    dd if="$REMOTE_DIR/$DUMP" bs="$BS" skip="$skip" status=none >> "$LOCAL" || true
done
truncate -s "$REMOTE_SIZE" "$LOCAL"

kubectl -n "$PROD_NS" exec "$POD" -- cat "$REMOTE_DIR/$GLOBALS" > "$OUT_DIR/$GLOBALS"

# ---- 3. verify --------------------------------------------------------------
echo "==> Verifying"
REMOTE_SHA=$(ksh "sha256sum $REMOTE_DIR/$DUMP" | awk '{print $1}')
LOCAL_SHA=$(sha256sum "$LOCAL" | awk '{print $1}')
if [[ "$REMOTE_SHA" != "$LOCAL_SHA" ]]; then
  echo "ERROR: checksum mismatch (remote $REMOTE_SHA != local $LOCAL_SHA)"; exit 1
fi
echo "$LOCAL_SHA  $DUMP" > "$LOCAL.sha256"
echo "    sha256 ok: $LOCAL_SHA"

# The dump is only trustworthy if it carries one TABLE DATA entry per chunk.
# Compare what's in the archive against what the live catalog says exists.
CHUNKS_IN_DB=$(ksh "psql -U \"\$POSTGRES_USER\" -d $PROD_DB -Atc 'select count(*) from _timescaledb_catalog.chunk'" | tr -d '\r')
CHUNKS_IN_DUMP=$(ksh "pg_restore -l $REMOTE_DIR/$DUMP | grep -c 'TABLE DATA _timescaledb_internal'" | tr -d '\r')
PUBLIC_IN_DB=$(ksh "psql -U \"\$POSTGRES_USER\" -d $PROD_DB -Atc \"select count(*) from pg_tables where schemaname='public'\"" | tr -d '\r')
PUBLIC_IN_DUMP=$(ksh "pg_restore -l $REMOTE_DIR/$DUMP | grep -c 'TABLE DATA public '" | tr -d '\r')
echo "    chunks: catalog=$CHUNKS_IN_DB  in dump=$CHUNKS_IN_DUMP"
echo "    public tables: prod=$PUBLIC_IN_DB  in dump=$PUBLIC_IN_DUMP"
[[ "$CHUNKS_IN_DUMP" -ge "$CHUNKS_IN_DB" ]] || { echo "ERROR: dump is missing chunk data"; exit 1; }
[[ "$PUBLIC_IN_DUMP" -ge "$PUBLIC_IN_DB" ]] || { echo "ERROR: dump is missing public tables"; exit 1; }

# Sidecar metadata. restore_backup.sh reads this to refuse a version-mismatched
# target and to check the restored counts, so a silent partial restore can't pass.
cat > "$OUT_DIR/$META" <<META_EOF
created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
source_namespace=$PROD_NS
source_pod=$POD
source_database=$PROD_DB
source_size=$DB_SIZE
postgres_version=$PG_VER
timescaledb_version=$TS_VER
chunks=$CHUNKS_IN_DB
public_tables=$PUBLIC_IN_DB
dump_bytes=$REMOTE_SIZE
dump_sha256=$LOCAL_SHA
dump_file=$DUMP
globals_file=$GLOBALS
META_EOF
echo "    wrote $OUT_DIR/$META"

if [[ "$KEEP_REMOTE" != "1" ]]; then
  echo "==> Removing dump from the pod's volume"
  ksh "rm -f $REMOTE_DIR/$DUMP $REMOTE_DIR/$GLOBALS $REMOTE_DIR/dump.log; rmdir $REMOTE_DIR 2>/dev/null || true"
fi

echo
echo "==> Done."
ls -lh "$LOCAL" "$OUT_DIR/$GLOBALS" "$OUT_DIR/$META"
echo "    Restore with: ./db/restore_backup.sh"
