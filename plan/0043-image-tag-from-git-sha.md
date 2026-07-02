# 0043 - image-tag-from-git-sha

Type: chore
Branch: chore/0043-image-tag-from-git-sha

## Goal

* Tag api-compute images with the short SHA of HEAD instead of hardcoded `v1.2` / `latest`.
* Deploy the exact image that was just built (no drift between build and apply).

## Context

* Manifests currently hardcode `:v1.2` (api, ingest, backfill-ingest) and `:latest` (backfill-basis, backfill-snapshots).
* `deploy-api.sh` already envsubsts `${IMAGE_REPO}`; extend to `${IMAGE_TAG}`.

## Approach

* Add `build.sh` at repo root: computes `IMAGE_TAG=$(git rev-parse --short HEAD)`, builds, ECR-logins, pushes, writes `.image-tag`.
* Update `ops/deploy/deploy-api.sh`: read `IMAGE_TAG` from `.image-tag`, pass to envsubst.
* Replace hardcoded tags with `${IMAGE_TAG}` in:
  * `ops/deploy/base/api/deploy.yml`
  * `ops/deploy/jobs/ingest_cronjob.yml`
  * `ops/deploy/jobs/backfill_ingest_job.yml`
  * `ops/deploy/jobs/backfill_basis_job.yml`
  * `ops/deploy/jobs/backfill_snapshots_job.yml`
* gitignore `.image-tag`.
* Do NOT touch: docker-compose.yml (dev flow unchanged).

## Acceptance

* [ ] `./build.sh --no-push` produces an image tagged `<repo>/ercotstress/api-compute:<sha>` and writes `.image-tag`.
* [ ] `ops/deploy/deploy-api.sh` applies a Deployment whose image tag matches `.image-tag`.
* [ ] All 5 manifests reference `${IMAGE_TAG}`; no hardcoded `:v1.2` or `:latest` remain.
