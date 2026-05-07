# K3s Deploy

* Assumes existing infrastructure setup on hetzner
* cert-manager with DNS-01 setup from 311crimemap project

* Rebuild images sans cache to force COPY:
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
