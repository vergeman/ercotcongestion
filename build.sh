#!/usr/bin/env bash
# Build & push the api-compute image to ECR, tagged with the short SHA of
# HEAD on the current branch. Writes the tag to .image-tag so
# ops/deploy/deploy-api.sh applies the exact image that was just pushed.
#
# Usage:
#   ./build.sh              # build + push
#   ./build.sh --no-push    # local build only, still writes .image-tag

set -euo pipefail

cd "$(dirname "$0")"

set -a
# shellcheck disable=SC1091
source .env
set +a

IMAGE_TAG="$(git rev-parse --short HEAD)"
IMAGE="${IMAGE_REPO}/ercotstress/api-compute:${IMAGE_TAG}"

echo ">> Building ${IMAGE}"
docker build -t "${IMAGE}" .

if [[ "${1:-}" != "--no-push" ]]; then
  echo ">> Logging in to ECR (${AWS_REGION})"
  aws ecr get-login-password --region "${AWS_REGION}" --profile "${AWS_PROFILE}" \
    | docker login --username AWS --password-stdin "${IMAGE_REPO}"

  echo ">> Pushing ${IMAGE}"
  docker push "${IMAGE}"
fi

echo "${IMAGE_TAG}" > .image-tag
echo ">> Wrote .image-tag: ${IMAGE_TAG}"
