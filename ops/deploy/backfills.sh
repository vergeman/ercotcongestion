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
  # Limit envsubst to ${IMAGE_REPO}; otherwise it eats shell vars ($START, $ep, …)
  # inside container command blocks before kubectl ever sees them.
  envsubst '${IMAGE_REPO}' < "jobs/$manifest" | kubectl apply -f -

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
  pricing)
    run_job backfill_pricing_job.yml backfill-pricing
    ;;
  snapshots)
    run_job backfill_snapshots_job.yml backfill-snapshots
    ;;
  basis)
    run_job backfill_basis_job.yml backfill-basis
    ;;
  all)
    run_job backfill_ingest_job.yml    backfill-ingest
    run_job backfill_pricing_job.yml   backfill-pricing
    run_job backfill_snapshots_job.yml backfill-snapshots
    run_job backfill_basis_job.yml     backfill-basis
    ;;
  *)
    echo "Usage: $0 [ingest|pricing|snapshots|basis|all]"
    exit 1
    ;;
esac

echo "==> Done."
