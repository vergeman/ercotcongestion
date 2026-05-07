#!/usr/bin/env bash
#
# Submit a snapshot Job. Usage:
#   ./scripts/snapshot.sh 2026-05-01 2026-05-02
#
# TAG=latest ECR_REPO=... \
  #  ./scripts/snapshot.sh 2026-05-01T00:00:00 2026-05-02T00:00:00
source ../../.env

set -euo pipefail

START="${1:?start required, e.g. 2026-05-01T00:00:00}"
END="${2:?end required, e.g. 2026-05-02T00:00:00}"
SUFFIX="${3:-$(date +%Y%m%d-%H%M%S)}"
TAG=latest

: "${IMAGE_REPO:?IMAGE_REPO not set}"
: "${TAG:?TAG not set (try: TAG=\$(git rev-parse --short HEAD))}"

export START END SUFFIX IMAGE_REPO TAG
envsubst < jobs/snapshot_job.yml.template | kubectl apply -f -

echo "Submitted snapshot-writer"
echo "Tail logs: kubectl -n ercotstress logs -f job/snapshot-writer-${SUFFIX}"
