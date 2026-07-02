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

* [x] `build.sh` at repo root: computes `IMAGE_TAG` from `git rev-parse --short HEAD`, builds, pushes, writes `.image-tag`. `.image-tag` gitignored.
* [x] `ops/deploy/deploy-api.sh` sources `.image-tag` and envsubsts `${IMAGE_TAG}`.
* [x] All 6 manifests (api deploy, ingest cronjob, 3 backfill jobs, snapshot template) reference `${IMAGE_TAG}`; no `:v1.2` or `:latest` remain.
* [x] `ops/README.md` documents `export IMAGE_TAG=$(cat ../../.image-tag)` for ad-hoc job applies.
