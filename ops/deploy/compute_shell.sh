#!/usr/bin/env bash
#
# Launch an api-compute pod with the compute-runs PVC mounted at /compute/runs
# and drop into an interactive shell.
#
# Usage:
#   ./compute_shell.sh
#
# Tunables (override via env before invoking):
#   CPU_REQUEST   Default "2"
#   CPU_LIMIT     Default "2"
#   MEM_REQUEST   Default "2Gi"
#   MEM_LIMIT     Default "8Gi"
#
# The pod runs `sleep infinity` so it stays alive for exec. Delete it when done:
#   kubectl -n ercotstress delete pod compute-shell

source ../../.env

set -euo pipefail

export IMAGE_TAG="$(cat ../../.image-tag)"

: "${IMAGE_REPO:?IMAGE_REPO not set}"
: "${IMAGE_TAG:?IMAGE_TAG not set (../../.image-tag empty?)}"

export CPU_REQUEST="${CPU_REQUEST:-2}"
export CPU_LIMIT="${CPU_LIMIT:-2}"
export MEM_REQUEST="${MEM_REQUEST:-2Gi}"
export MEM_LIMIT="${MEM_LIMIT:-8Gi}"

export IMAGE_REPO
envsubst < jobs/compute_shell_pod.yml.template | kubectl apply -f -

echo "Waiting for compute-shell pod to be ready..."
kubectl -n ercotstress wait --for=condition=Ready pod/compute-shell --timeout=300s

echo "Exec'ing into compute-shell (image tag ${IMAGE_TAG})"
kubectl -n ercotstress exec -it compute-shell -- bash
