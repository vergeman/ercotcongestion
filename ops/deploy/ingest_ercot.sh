#!/usr/bin/bash

set -euo pipefail

cd "$(dirname "$0")"

source ../../.env

export IMAGE_REPO
export IMAGE_TAG="$(cat ../../.image-tag)"

: "${IMAGE_REPO:?IMAGE_REPO not set}"
: "${IMAGE_TAG:?IMAGE_TAG not set (../../.image-tag empty?)}"

envsubst '${IMAGE_REPO} ${IMAGE_TAG}' < jobs/ingest_cronjob.yml | kubectl apply -f -
