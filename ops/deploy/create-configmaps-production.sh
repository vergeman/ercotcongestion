#!/usr/bin/bash

source ../../.env

kubectl delete configmap postgres-migrations -n ercotstress --ignore-not-found=true
kubectl create configmap postgres-migrations -n ercotstress --from-file=../../db/migrations

kubectl apply -f ./base/configmap.yml
