# 007 - Ercot Ingest Additional Data

Type: feat
Branch: feat/0007-ercot-ingest-additional-data

## Goal

* Add additiona ERCOT datasets. Similar to existing code, need to repeatedly
  fetch and store datasets. Search web to generate proper report/prefix in api
  url, based on mpattern in `/ercot_ingest`

  * NP4-190-CD: DAM SPP        → `/np4-190-cd/dam_stlmnt_pnt_prices`
  * NP4-523-CD: DAM Lambda     → `/np4-523-cd/dam_system_lambda`
  * NP6-788-CD: RT LMP         → `/np6-788-cd/lmp_node_zone_hub`
  * NP6-322-CD: SCED Lambda    → `/np6-322-cd/sced_system_lambda`
  * NP3-561-CD: Load Forecast  → `/np3-561-cd/7d_load_fcast_by_wzn`

* create sql migration files in `db/migration` to capture each respective
  dataset in tables and fields

* `loader.py`: expand for new datasets, keeping same ON CONFLICT pattern
  * have similar print output indicating fetch and insert

* `backfill.py`: register the 5 new endpoints in `ENDPOINTS` (path / loader /
  param config). Adds `dam_spp`, `dam_lambda`, `rt_lmp`, `sced_lambda`,
  `load_forecast` choices to `--endpoint`.

* `live_updater.py`: no change. It loops over `ENDPOINTS` from `backfill.py`,
  so the new datasets are picked up automatically by the 15-min cycle.

* `/ops/deploy/jobs/ingest_cronjob.yml`: no change. The existing
  `activeDeadlineSeconds: 600` is generous for the added throughput (small per-
  endpoint payloads on a 2hr window).

* Bugfix: ERCOT's public API interprets naive datetime filters as Central Time.
  Sending UTC values made the 2hr window land ~5h in the future -> 0 rows. This
  silently breaks datetime-filter endpoints in `live_updater`. Fixed in
  `backfill.py::backfill_one_window` by converting `start`/`end` to
  `America/Chicago` (CST) before formatting datetime params.
  * Data migration plan created for next sprint.

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
