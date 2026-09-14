# Pending — Drop legacy implied shift factors

Type: chore

## Goal

* Safely remove the legacy `implied_shift_factors` table and reclaim its disk.

## Context

* Production has 90/90 canonical weekly NPZ artifacts and provenance on 672/672 daily artifacts.
* Runtime readers use artifacts; the legacy table remains only as the completed backfill source.
* The first post-cutover weekly producer run has not yet been observed.

## Approach

1. After each of the next two Sunday `ercot-map-refresh` jobs, verify one new `sf_window_meta` row has exactly one new `sf_window_artifact` row, with a decodable payload.
2. After each refresh, verify the daily forecast publishes normally and its new `forecast_sf_artifact` row records the selected map run/window.
3. Before the drop, create and verify a fresh off-host logical backup, including its checksum and restore metadata.
4. Record `pg_total_relation_size` for the legacy table/index, database size, and volume free space.
5. Add and apply a forward migration that drops `implied_shift_factors` and `idx_implied_shift_factors_run_window`; do not drop `sf_window_meta` or `constraint_geo`.
6. Verify no runtime source, CronJob, or deployed image references the table. Retire the backfill utility only after the drop is confirmed.
7. Record relation/database/volume sizes after the drop. Schedule `pg_repack` only if space is not returned, with `VACUUM FULL` reserved for a maintenance window.

## Acceptance

* [ ] Two post-cutover weekly map refreshes each produce one decodable canonical artifact and healthy daily forecasts.
* [ ] A fresh off-host backup is checksum-verified before the drop.
* [ ] The legacy table and index are removed by a forward migration only.
* [ ] Reclaimed database and volume space is measured and recorded.
