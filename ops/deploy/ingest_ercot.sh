#!/usr/bin/bash

source ../../.env

export $(grep -E '^(IMAGE_REPO)' ../../.env)
envsubst  '${IMAGE_REPO}' < jobs/ingest_cronjob.yml | kubectl apply -f -
