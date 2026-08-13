# 0129-0001 - ingest-guards

Type: fix
Branch: fix/0129-0001-ingest-guards
Depends on: none — start here

## Goal

* Purge the NaN `gen_*` rows already sitting in `wind_hourly_regional` and pin a
  regression test so they cannot come back.
* Unstall the `load_by_zone` ingest, which stops at 2026-07-22.
* Refresh `constraint_geo.zone_shares`, stamped 2025-12-13 against a 2026-07-28
  delivery day.

## Context

* **The ingest guard already exists.** `ercot_ingest/loaders.py::_f` (~line 705) coerces
  NaN to `None`, every `gen_*` column in `load_wind_hourly` routes through it, and its
  docstring records the original finding — *"8 rows in `wind_hourly_regional` and 6 in
  `solar_hourly_regional` were already storing NaN when this was found."* So this is a
  **data repair of rows written before that fix**, not a new guard. Do not re-add one.
* Why it matters: Postgres stores NaN in `DOUBLE PRECISION` as a **non-null value**, so
  `IS NULL` misses it and any aggregate poisons to NaN. NaN compares false to
  everything, so a sort over a series containing one returns an unsorted list and every
  percentile taken from it is silently wrong — which is what the Context panel reads.
* Affected days are DST spring-forward: 2025-03-09, 2026-03-08, 2026-04-03. The
  prototype drops them at read time; production should not have to.
* `load_by_zone` stalling means the delivery day has no actual, so the Conditions panel
  ranks a forecast against a window of forecasts and says nothing about realized load.
* `constraint_geo` is refreshed by `ops/deploy/jobs/map_refresh_cronjob.yml` (which runs
  `compute/jobs/weekly_map.py --persist-sf` then `compute.sf.geo_persist`). Establish
  why it is eight months stale before assuming a re-run fixes it.

## Approach

* Work in: `ercot_ingest/loaders.py`, `db/`, `ops/deploy/jobs/map_refresh_cronjob.yml`
* Find the damage first — `WHERE gen_x <> gen_x` is the only predicate that finds NaN
  (`IS NULL` will not). Count per column and per day across `wind_hourly_regional` and
  `solar_hourly_regional` before changing anything.
* Repair by re-ingesting the affected days through the current loader, which already
  coerces correctly. Prefer re-ingest over an `UPDATE … SET NULL` so the row's other
  columns are re-derived from source rather than left half-repaired.
* Add a regression test that feeds a frame containing NaN through `load_wind_hourly` and
  asserts the persisted value `IS NULL` — pinning `_f`'s behaviour so a future
  refactor cannot quietly drop it.
* Diagnose `load_by_zone` separately: whether the 2026-07-22 stop is a source-feed
  change, a loader exception, or a scheduling gap. Do not paper over it with a backfill
  until the cause is known, or it will stall again.
* Re-run the map refresh and confirm `constraint_geo.window_start` advances. If it does
  not, the cronjob is the bug, not the data.
* Do NOT touch: `_f` itself, the modeling path, or any panel that currently drops these
  rows at read time — the read-side drops stay until the data is verified clean.

## Acceptance

* [ ] `SELECT count(*) FROM wind_hourly_regional WHERE gen_system_wide <> gen_system_wide` returns 0, and the same holds for every `gen_*` column and for `solar_hourly_regional`.
* [ ] A regression test asserts NaN input to `load_wind_hourly` persists as SQL NULL.
* [ ] `load_by_zone` has rows through the current delivery day; the root cause of the 2026-07-22 stop is written down in the PR.
* [ ] `constraint_geo` reports a `window_start` within the last refresh cycle, not 2025-12-13.
* [ ] Percentiles computed over a DST spring-forward day match a hand-checked value.
