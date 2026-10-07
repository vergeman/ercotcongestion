# Completed — Drop legacy implied shift factors

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

* [x] Two post-cutover weekly map refreshes each produce one decodable canonical artifact and healthy daily forecasts.
* [x] A fresh off-host backup is checksum-verified before the drop.
* [x] The legacy table and index are removed by a forward migration only.
* [x] Reclaimed database and volume space is measured and recorded.

## Production completion — 2026-10-05

* Sunday jobs `ercot-map-refresh-29842200` (September 27) and `ercot-map-refresh-29852280` (October 4) completed successfully, each writing one canonical artifact. Both payloads passed codec, shape, label, and value validation; subsequent forecasts recorded the corresponding map window.
* Fresh off-host backup: `db/backups/2026-10-05/ercot-20261005-1647.dump`, 4,365,870,359 bytes. SHA-256 verified locally: `9897fca0a6173c2b620496b16ec9d08b9a751fe3eacb9273ca167b646b654a5c`. Restore metadata and roles dump are present; no test restore was performed.
* Applied `db/migrations/53_drop_implied_shift_factors.sql` at approximately 22:17 UTC. Verified both table and index are absent. The migration uses bounded lock/statement timeouts, checks weekly artifact coverage, and does not cascade.
* Retained 93 `sf_window_meta` rows, 93 canonical weekly artifacts, 95,282 `constraint_geo` rows, and 714 daily artifacts with provenance.
* Runtime source and deployed CronJobs have no legacy-table consumers; the only SQL reference in the deployed application image is the retired backfill utility. Removed that utility from source after confirming the drop; its removal from the image will take effect on the next application deployment.

| Measurement | Before (bytes) | After (bytes) |
| --- | ---: | ---: |
| Legacy table and indexes (`pg_total_relation_size`) | 18,471,649,280 | 0 (relation absent) |
| Legacy heap | 12,159,950,848 | 0 |
| Legacy indexes | 6,308,306,944 | 0 |
| Database | 36,004,925,923 | 17,533,276,643 |
| Volume available | 40,820,965,376 | 59,292,786,688 |

* Recovered 18,471,649,280 database bytes (17.2 GiB) and 18,471,821,312 volume bytes. Space returned immediately; no `pg_repack` or `VACUUM FULL` is needed.
* Post-drop production `/map/summary` returned HTTP 200.

## Docker Compose development completion — 2026-10-05

* Verified all 79 weekly metadata rows have canonical artifacts, then applied the same forward migration to the `db` service's `ercot` database.
* Verified legacy table and index are absent; retained 79 weekly metadata rows, 79 weekly artifacts, and 80,602 geography rows.
* Database size decreased from 21,904,735,255 to 10,491,362,327 bytes, reclaiming 11,413,372,928 bytes (10.6 GiB).
* Development `/map/summary` returned HTTP 200 after the drop.
