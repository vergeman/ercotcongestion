#!/usr/bin/env bash
#
# Apply the scheduled forecast and map-refresh CronJobs.
#
# Usage:
#   ./model_cronjobs.sh [forecast|forecast-preview|map-refresh|all]
#
# `forecast` is the 17:00 UTC final (horizon 1) tick; `forecast-preview` is the
# 19:45 UTC preview (horizon 2, t+2) tick. `all` applies every cronjob.

set -euo pipefail

cd "$(dirname "$0")"

set -a
source ../../.env
set +a

apply_cronjob() {
  local manifest=$1

  echo "==> Applying jobs/$manifest"
  envsubst '${IMAGE_REPO} ${IMAGE_TAG}' < "jobs/$manifest" | kubectl apply -f -
}

export IMAGE_TAG="$(cat ../../.image-tag)"
: "${IMAGE_REPO:?IMAGE_REPO not set}"
: "${IMAGE_TAG:?IMAGE_TAG not set (../../.image-tag empty?)}"

case "${1:-all}" in
  forecast)
    apply_cronjob forecast_cronjob.yml
    ;;
  forecast-preview)
    apply_cronjob forecast_preview_cronjob.yml
    ;;
  map-refresh)
    apply_cronjob map_refresh_cronjob.yml
    ;;
  all)
    apply_cronjob forecast_cronjob.yml
    apply_cronjob forecast_preview_cronjob.yml
    apply_cronjob map_refresh_cronjob.yml
    ;;
  *)
    echo "Usage: $0 [forecast|forecast-preview|map-refresh|all]" >&2
    exit 1
    ;;
esac

echo "==> Done."
