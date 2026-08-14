#!/usr/bin/env bash
# Backfill the materialized v6 Brief grade in contiguous, resumable 30-day
# production batches. Run this *inside* a production compute-shell pod after
# migrations 42 and 43 have been applied.
#
# Usage:
#   compute/jobs/backfill_brief_grade_prod.sh [end-date] [start-date]
#
# With no arguments, end-date is two Chicago days ago (the conservative latest
# fully settled delivery day) and start-date is 2025-01-01. Re-running any
# batch is safe: materialize_brief_grade upserts by run/date/horizon/subject.

set -euo pipefail

RUN_ID="mu-all-v1"
HORIZON="1"
BATCH_DAYS="30"
START_DATE="${2:-2025-01-01}"
END_DATE="${1:-$(TZ=America/Chicago date -d '2 days ago' +%F)}"

if [[ "${START_DATE}" > "${END_DATE}" ]]; then
  echo "start-date must not be after end-date" >&2
  exit 2
fi

current_end="${END_DATE}"
while [[ "${current_end}" > "${START_DATE}" || "${current_end}" == "${START_DATE}" ]]; do
  batch_start="$(date -d "${current_end} - $((BATCH_DAYS - 1)) days" +%F)"
  if [[ "${batch_start}" < "${START_DATE}" ]]; then
    batch_start="${START_DATE}"
  fi
  batch_days="$(( ($(date -d "${current_end}" +%s) - $(date -d "${batch_start}" +%s)) / 86400 + 1 ))"
  echo "${batch_start} through ${current_end} (${batch_days} days)"
  python -m compute.jobs.materialize_brief_grade \
    --run-id "${RUN_ID}" --delivery-date "${current_end}" \
    --horizon "${HORIZON}" --days "${batch_days}"

  current_end="$(date -d "${batch_start} - 1 day" +%F)"
done
