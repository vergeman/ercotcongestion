# K3s Deploy

* Assumes existing infrastructure setup on Hetzner (terraform, see 311crimemap)

* cert-manager with DNS-01 setup from pre-existing 311crimemap project

* NB: Rebuild images sans cache to force COPY:
  * e.g. `docker compose build --no-cache api`
  * `docker build -f api/Dockerfile -t {$IMAGE_REPO}/ercotstress/api:{$TAG} .`


1. `./create-secrets.sh`

2. Refresh aws ecr: `aws ecr get-login-password --region $AWS_REGION --profile
   $AWS_PROFILE | docker login --username AWS --password-stdin $IMAGE_REPO`

3. `./create-configmaps.sh`
  * postgres migrations
  * postgres env vars,  api path env vars

4. postgres statefulset
  * `kubectl apply -f base/postgres/statefulset.yml`

5. postgres service
  * `kubectl apply -f base/postgres/service.yml`

6. api deployment -> service -> certificate -> ingress:
  * `./deploy-api.sh`

## Jobs

* Manifests reference `${IMAGE_TAG}`. Before applying a job manifest, export
  the tag written by `./build.sh` at repo root:
  * `export IMAGE_TAG=$(cat ../../.image-tag)`

* `ingest_cronjob.sh`: starts a 15-min `live-updater.py` loop
  * check `ercot_ingest/proxy/worker.js`


## Reset DB To local

* NB: this drops prod db and re-imports
* `deploy/import_database.sh`: just run
  * likely need to restart ap
