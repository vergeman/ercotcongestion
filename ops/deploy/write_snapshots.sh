#!/usr/bin/env bash
#
# Submit a snapshot Job to run compute/write_snapshots.py against a window.
#
# Usage:
#   ./write_snapshots.sh START END [SUFFIX]
#
# SUFFIX becomes part of the Kubernetes Job name (snapshot-writer-<SUFFIX>).
# Job names must be unique in the namespace, so:
#   - pick something recognizable when you'll want to find it later
#     (e.g. "may1", "backfill-2025", "test-derate-sweep")
#   - if omitted, defaults to a UTC timestamp (YYYYMMDD-HHMMSS) so back-to-back
#     runs never collide
# Jobs auto-delete 24h after completion (ttlSecondsAfterFinished).
#
#
# Full example — backfill Jan 2025 through May 2026, tagged so you can find it:
#
#   cd ops/deploy
#   ./write_snapshots.sh 2025-01-01T00:00:00 2026-05-07T00:00:00 backfill-2025
#
#   kubectl -n ercotstress logs -f job/snapshot-writer-backfill-2025
#   kubectl -n ercotstress delete job snapshot-writer-backfill-2025   # when done
#
# IMAGE_TAG is read from ../../.image-tag (same pattern as deploy-api.sh).
#
# Tunables (override via env before invoking):
#   DEADLINE_SECONDS  Job activeDeadlineSeconds. Default 14400 (4h). For a
#                     multi-month backfill, set to e.g. 172800 (48h).
#   CPU_REQUEST       Default "2"
#   CPU_LIMIT         Default "2"
#   MEM_REQUEST       Default "2Gi"
#   MEM_LIMIT         Default "8Gi". Bump if OOMKilled.
#   HIGHS_THREADS     Default = CPU_LIMIT. Passed as env into the pod.
#
# Throughput notes (measured 2026-07-01):
#   - HiGHS chooses serial dual simplex for this LP shape; PAMI and IPM
#     are both slower here (IPM ~1.8x slower). Solve pins ~1 core, so
#     CPU_LIMIT above ~2 is wasted headroom (LMPs match to 4 decimals
#     across solvers, so no correctness argument to change).
#   - Build overhead is ~9s per chunk regardless of chunk size. To amortize,
#     try a bigger --chunk-size (default 6). Requires patching the command
#     args in jobs/snapshot_job.yml.template.
#   - The real throughput lever is running multiple Jobs over non-overlapping
#     windows in parallel — bus_snapshots/snapshot_meta UPSERT is idempotent,
#     so concurrent writers on disjoint ts ranges are safe.
#
# Backfill example (single job):
#   DEADLINE_SECONDS=172800 \
#     ./write_snapshots.sh 2025-01-01 2026-05-07 backfill-2025
#
# Parallel backfill example (two jobs, ~2x throughput on a multi-core node):
#   DEADLINE_SECONDS=172800 \
#     ./write_snapshots.sh 2025-01-01 2025-06-30 backfill-h1
#   DEADLINE_SECONDS=172800 \
#     ./write_snapshots.sh 2025-07-01 2025-12-31 backfill-h2
source ../../.env

set -euo pipefail

START="${1:?start required, e.g. 2026-05-01T00:00:00}"
END="${2:?end required, e.g. 2026-05-02T00:00:00}"
SUFFIX="${3:-$(date +%Y%m%d-%H%M%S)}"

export IMAGE_TAG="$(cat ../../.image-tag)"

: "${IMAGE_REPO:?IMAGE_REPO not set}"
: "${IMAGE_TAG:?IMAGE_TAG not set (../../.image-tag empty?)}"

export DEADLINE_SECONDS="${DEADLINE_SECONDS:-14400}"
export CPU_REQUEST="${CPU_REQUEST:-2}"
export CPU_LIMIT="${CPU_LIMIT:-2}"
export MEM_REQUEST="${MEM_REQUEST:-2Gi}"
export MEM_LIMIT="${MEM_LIMIT:-5Gi}"
export HIGHS_THREADS="${HIGHS_THREADS:-$CPU_LIMIT}"

export START END SUFFIX IMAGE_REPO
envsubst < jobs/snapshot_job.yml.template | kubectl apply -f -

echo "Submitted snapshot-writer-${SUFFIX} (image tag ${IMAGE_TAG})"
echo "Tail logs: kubectl -n ercotstress logs -f job/snapshot-writer-${SUFFIX}"
