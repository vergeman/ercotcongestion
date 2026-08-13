#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

set -a
source ../../.env
set +a

NS=ercotstress

run_job() {
  local manifest=$1
  local job_name=$2

  echo "==> Ensure Dates Set in Job Manifests!"

  # Jobs are immutable; a prior run (even a failed apply) leaves the resource
  # around. Delete first so we can re-apply cleanly.
  # kubectl -n "$NS" delete job "$job_name" --ignore-not-found

  echo "==> Applying $manifest"
  export IMAGE_TAG="$(cat ../../.image-tag)"
  : "${IMAGE_REPO:?IMAGE_REPO not set}"
  : "${IMAGE_TAG:?IMAGE_TAG not set (../../.image-tag empty?)}"

  # Limit envsubst to ${IMAGE_REPO} ${IMAGE_TAG}; otherwise it eats shell vars
  # ($START, $ep, …) inside container command blocks before kubectl ever sees them.
  envsubst '${IMAGE_REPO} ${IMAGE_TAG}' < "jobs/$manifest" | kubectl apply -f -

  echo "==> Tailing logs for $job_name (will block until job finishes)"
  kubectl -n "$NS" wait --for=condition=ready --timeout=300s pod -l job-name="$job_name" || true
  kubectl -n "$NS" logs -f "job/$job_name" || true

  echo "==> Verifying $job_name completed successfully"
  kubectl -n "$NS" wait --for=condition=complete --timeout=10s "job/$job_name"

  echo "==> Cleaning up $job_name"
  kubectl -n "$NS" delete job "$job_name"
}

case "${1:-all}" in
  ingest)
    run_job backfill_ingest_job.yml backfill-ingest
    ;;
  outages)
    run_job backfill_outages_job.yml backfill-outages
    ;;
  essp)
    run_job backfill_essp_job.yml backfill-essp
    ;;
  all)
    run_job backfill_ingest_job.yml    backfill-ingest
    run_job backfill_outages_job.yml   backfill-outages
    run_job backfill_essp_job.yml      backfill-essp
    ;;
  *)
    echo "Usage: $0 [ingest|outages|essp|all]"
    exit 1
    ;;
esac

echo "==> Done."
