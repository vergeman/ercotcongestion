#!/usr/bin/bash

source ../../.env

# Initial Namespaces
kubectl apply -f ./base/namespace.yml

# Hetzner
kubectl delete secret hcloud --ignore-not-found=true --namespace=kube-system
kubectl create secret generic hcloud --namespace=kube-system --from-literal=token=$HCLOUD_TOKEN


# ECR
kubectl delete secret regcred -n ercotstress --ignore-not-found=true
kubectl create secret docker-registry regcred \
        -n ercotstress \
        --docker-server=$IMAGE_REPO \
        --docker-username=AWS \
        --docker-password=`aws ecr get-login-password --profile $AWS_PROFILE --region $AWS_REGION` \
        --docker-email=abc@abc.com

# POSTGRES
kubectl delete secret postgres-credentials -n ercotstress --ignore-not-found=true
kubectl create secret generic postgres-credentials \
        -n ercotstress \
        --from-literal=PG_USER=$PG_USER \
        --from-literal=PG_PASSWORD=$PG_PASSWORD

#
# ERCOT INGEST / PROXY
#

# Cloudflare: Token in env for Wrangler put secret, Wrangler for worker proxy
kubectl delete secret ercot-ingest-secrets -n ercotstress --ignore-not-found=true
kubectl create secret generic ercot-ingest-secrets \
        -n ercotstress \
        --from-literal=CLOUDFLARE_API_TOKEN=$CLOUDFLARE_API_TOKEN \
        --from-literal=WRANGLER_PROXY_SECRET=$WRANGLER_PROXY_SECRET \
        --from-literal=PROXY_BASE=$PROXY_BASE \
        --from-literal=ERCOT_USERNAME=$ERCOT_USERNAME \
        --from-literal=ERCOT_PASSWORD=$ERCOT_PASSWORD \
        --from-literal=ERCOT_SUBSCRIPTION_KEY=$ERCOT_SUBSCRIPTION_KEY

# CERT ISUER
kubectl create secret generic cloudflare-api-token-secrets \
        -n ercotstress \
        --from-literal=api-token=$CLOUDFLARE_CERT_API_TOKEN

# API: configmap

# WEB
# VITE_API_BASE set on Cloudflare Pages
