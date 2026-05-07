#!/usr/bin/bash

export $(grep -E '^(IMAGE_REPO)' ../../.env)
envsubst '${IMAGE_REPO}' < base/api/deploy.yml | kubectl apply -f -

kubectl apply -f base/api/service.yml
kubectl apply -f base/cert-issuer.yml
kubectl apply -f base/api/certificate.yml
kubectl apply -f base/api/ingress.yml
