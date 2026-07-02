#!/usr/bin/bash

export $(grep -E '^(IMAGE_REPO)' ../../.env)
export IMAGE_TAG="$(cat ../../.image-tag)"
envsubst '${IMAGE_REPO} ${IMAGE_TAG}' < base/api/deploy.yml | kubectl apply -f -

kubectl apply -f base/api/service.yml
kubectl apply -f base/cert-issuer.yml
kubectl apply -f base/api/certificate.yml
kubectl apply -f base/api/ingress.yml
