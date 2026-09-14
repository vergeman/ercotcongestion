# 0213 - Replace relational SF cells with weekly NPZ artifacts

Type: refactor
Branch: refactor/0213-sf-window-npz-artifacts

## Goal

* Replace the row-per-cell `implied_shift_factors` store with one self-describing, dense float32 NPZ artifact per weekly SF window.
* Preserve the weekly-map → daily-forecast boundary: load the causal weekly artifact, perform day-specific alignment, and persist the served daily SF + E_mu artifact unchanged.
* Persist exact weekly-SF provenance on every daily forecast artifact, then remove the legacy table only after all producers and consumers have cut over.

## Context

* Production stores about 90 weekly map vintages as 79M long-format cells (about 17 GB); the same dense float32 matrix is about 4.6 MB before NPZ compression for the current largest window.
* `/matrix`, `/map/reach`, `/map/exposures`, and ranked daily map paths already decode per-day `forecast_sf_artifact` blobs; `/map/overview` is the sole live API reader of raw weekly SF cells.
* A daily artifact is a served snapshot and can omit points absent from that day's congestion panel; it must not become the canonical weekly SF source.

## Approach

* Work in: `db/migrations/`, `compute/projection/codecs.py`, `compute/sf_map/storage/`, `compute/jobs/weekly_map.py`, `compute/jobs/daily_forecast.py`, `compute/sf_map/geography/persist.py`, `api/services/map/`, and their focused tests.
* Do NOT change: the `/matrix` or `/map/reach` response contracts, daily artifact payload format, SF numerical fitting method, or historic daily-artifact retention.

### 1. Add the canonical weekly-artifact and provenance schema

* Add an additive migration creating `sf_window_artifact(run_id, window_start, sf_npz, codec_version, created_at)`, keyed by `(run_id, window_start)` and linked to `sf_window_meta` so a map window cannot have metadata without its canonical payload after cutover.
* Add nullable `sf_map_run_id`, `sf_window_start`, and `sf_window_end` columns to `forecast_sf_artifact`; use an all-null-or-all-present constraint for the three provenance fields. Preserve the current primary key `(run_id, delivery_date, horizon)`.
* Define an SF-only codec beside `SfMuArtifact`: an immutable artifact with UTF-8 constraint/SP vocabularies and a dense `float32[n_constraints, n_settlement_points]` matrix. Require finite-or-NaN values, stable vocabulary ordering, `allow_pickle=False`, and round-trip tests for changed matrix shapes and labels.
* Store the full calculated float32 weekly matrix before the legacy `--sf-threshold` filtering. Define loader modes explicitly: forecast projection receives thresholded/zero-filled values equivalent to today; structural geography can request the thresholded-present representation it currently receives from `fill_value=None`.

### 2. Backfill and validate the additive store

* Add an idempotent, resumable backfill command that reads one legacy `(run_id, window_start)` slice at a time, rebuilds its current zero-filled matrix, writes `sf_window_artifact`, and logs row count, shape, SHA-256 of NPZ bytes, and compressed size. Do not load all windows into memory.
* Compare the decoded backfill artifact against `load_window_sf(..., fill_value=0)` for every existing production window: identical ordered labels, shape, finite values, and thresholded projection output. Report any missing `sf_window_meta`/legacy counterpart as an error, not a silently empty artifact.
* Backfill historic `forecast_sf_artifact` provenance only after producing a dry report: infer the causal `map-v1` window from `sf_window_meta` for each delivery day, require exactly one match, and leave/report rows that cannot be proven. Future writes must never rely on this inference.
* Record before/after relation sizes and artifact-size distribution so the migration demonstrates the expected storage reduction without assuming a compression ratio.

### 3. Dual-write new weekly maps and persist exact daily provenance

* Change `weekly_map --persist-sf` to serialize the in-memory `RefitWindow.SF` to `sf_window_artifact` in the same transaction as `sf_window_meta`; retain the legacy `copy_sf_rows` write temporarily for comparison. Update `--rebuild` to clear and rebuild both stores atomically.
* Keep `sf_window_meta` as the authoritative causal-window selector. Make the artifact writer reject duplicate/missing metadata keys and log artifact dimensions, uncompressed float bytes, compressed bytes, and window bounds rather than legacy row counts.
* Extend `ForecastResult` with the selected `sf_map_run_id`, `sf_window_start`, and `sf_window_end`. Persist those values with the daily blob in the same transaction as `forecast_nodal` and the forecast-current pointer.
* Assert in focused tests that a new daily artifact records the exact window selected by `resolve_sf_window`, including a historical/backfill day and a day with a retired settlement point.

### 4. Move every weekly-SF reader to artifacts

* Replace `load_window_sf`'s SQL unpivot/pivot query with an artifact load/decode keyed by `(run_id, window_start)`. Keep its public alignment and fill-value behavior until all callers have migrated, then rename/document it as the weekly-artifact loader.
* Update `daily_forecast` and forecast backfills to load the canonical weekly artifact. Preserve the existing day-specific removal of settlement points absent from the congestion panel before `forecast_sf_artifact` is built.
* Update `geography.persist` to decode each weekly artifact and regenerate `constraint_geo`; retain its independent, rerunnable workflow and verify its threshold semantics against the legacy output.
* Update `/map/overview` to decode the newest weekly artifact and calculate the existing top-constraint/top-node response in memory. Add a process-local, byte-bounded cache keyed by `(run_id, window_start)`; invalidate naturally when `sf_window_meta` resolves a new latest window.
* Change map fit/provenance reads to prefer the persisted daily `sf_map_run_id`/window fields, with a temporary inference fallback only for historic rows not yet backfilled. Keep `/matrix`, `/map/reach`, `/map/exposures`, and daily ranked paths on their existing daily artifacts.

### 5. Verify cutover, remove the legacy store, and reclaim disk

* Run the production-like dual-write period for at least two weekly refreshes. For each new window, compare decoded artifact vs legacy `load_window_sf` outputs and compare daily forecast panel/artifact results produced from each source before allowing cutover.
* Remove the legacy writer and every remaining runtime reference to `implied_shift_factors`; update README, CLI help, migration comments, and job logs from “rows”/thresholded table language to canonical weekly artifacts.
* Add a final forward-only migration that drops `implied_shift_factors` and `idx_implied_shift_factors_run_window` only after the backfill audit, provenance audit, and code search prove no consumer remains. Retain `sf_window_meta` and `constraint_geo`.
* Schedule `pg_repack` for the dropped table/index footprint (or a maintenance-window `VACUUM FULL` fallback) after the drop; report database and volume space recovered. Do not run either operation as part of an application migration.

## Acceptance

* [ ] Each `sf_window_meta` row for an active run has exactly one decodable weekly NPZ artifact with matching run/window identity and stable labels.
* [ ] A complete production backfill reproduces every legacy zero-filled SF window and logs size/shape/checksum evidence without exhausting worker memory.
* [ ] New weekly maps dual-write matching artifact and legacy representations; a new daily forecast records `sf_map_run_id`, `sf_window_start`, and `sf_window_end` atomically with its served blob.
* [ ] Daily forecasts, backfills, `constraint_geo`, and `/map/overview` read weekly artifacts; `/matrix`, `/map/reach`, `/map/exposures`, and daily ranking remain behaviorally unchanged.
* [ ] Artifact-backed `/map/overview` preserves its current response shape, top-K ordering/floors, and map metadata, with one decode per current window per API process under normal cache operation.
* [ ] Focused codec, storage, weekly-map, forecast, geography, and map API tests cover variable constraint/SP vocabularies, threshold behavior, historic causal selection, provenance, cache invalidation, and legacy/artifact equivalence.
* [ ] No runtime code, job, or documentation reference to `implied_shift_factors` remains when the final drop migration lands; production disk reclamation is performed separately and measured.
