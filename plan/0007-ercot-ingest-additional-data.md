# 007 - Ercot Ingest Additional Data

Type: feat
Branch: feat/0007-ercot-ingest-additional-data

## Goal

* Add additiona ERCOT datasets. Similar to existing code, need to repeatedly
  fetch and store datasets. Search web to generate proper report/prefix in api
  url, based on mpattern in `/ercot_ingest`

  * NP4-190-CD: DAM SPP
  * NP4-523-CD: DAM Lambda
  * NP6-788-CD: RT LMP
  * NP6-322-CD: RT Lambda
  * NP3-561-CD: Load Forecast

* create sql migration files in `db/migration` to capture each respective
  dataset in tables and fields

* `loader.py`: expand for new datasets, keeping same ON CONFLICT pattern
  * have similar print output indicating fetch and insert

* backfill and k3s job will be done in next sprint

## Context

* Current datasets lack pricing information for revised project direction
* Calculate congestion from variations of LMP - system lambda


## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->
* Work within the ercot_ingest service (`/ercot_ingest/ErcotClient`)
* Follow examples:
  * `ErcotClient.py` logic to fetch
  * `db/migrations` for database migrations
  * `loaders.py` for insert code and raw data manipulation
  * `backfill.py` for bulk data insert by date range
  * `/ops/deploy/jobs/ingest_cronjob.yml`: k3s cronjob - extend to cover new
    datasets.
