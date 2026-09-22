# 0217 - forecast-range-compaction

Type: refactor
Branch: refactor/0217-forecast-range-compaction

## Goal

* Reduce `/forecast_range` JSON repetition by sharing settlement-point IDs across the response.
* Preserve stable per-hour settlement-point alignment when forecast coverage changes.
* Keep map consumers on their existing expanded per-SP cache shape.

## Context

* `/ercot_range` already sends `sp_ids` once and aligned nullable value arrays per interval.
* `/forecast_range` previously repeated `sp_id` and object keys for every settlement point in every hour.
* The measured 25-hour sample had 1,120 settlement points per hour; the compact shape reduces raw JSON from about 1.42 MB to 170 KB.

## Approach

### Commit 1 — compact the forecast API response

* Work in: `api/schemas/forecast.py`, `api/services/forecast_range.py`, and `api/models.py`.
* Replace per-entry forecast-SP objects with a response-level `sp_ids` array and entry-level nullable `congestion` arrays aligned by index.
* Build the sorted union of settlement points in the selected window and fill unavailable values with `null`, so added or removed SPs never shift another point’s position.
* Retain interval timestamps, system lambda, lambda provenance, horizons, run ID, and existing rounding behavior.
* Do NOT touch: forecast selection, horizon coalescing, database query shape, or omitted-window behavior.

### Commit 2 — expand at web API boundaries

* Work in: `web/src/api/types/map.ts`, `web/src/api/prefetch.ts`, and `web/src/components/map/useMiniMapData.ts`.
* Model the compact wire response separately from the expanded forecast cache entry.
* Expand `sp_ids` and each interval’s `congestion` values into the existing `{ sp_id, forecast_congestion }` cache rows; preserve `null` for missing values.
* Update mini-map’s direct forecast request path to read indexed values and skip null congestion.
* Do NOT touch: map rendering, color scales, topology identifiers, or settled `/ercot_range` behavior.

### Commit 3 — pin compact-index behavior

* Work in: `api/tests/test_forecast.py`.
* Cover an SP leaving and a different SP entering between adjacent intervals; assert their shared positions contain `null` rather than shifting values.
* Run focused forecast API tests plus web TypeScript checking and linting.

## Acceptance

* [x] `/forecast_range` returns one `sp_ids` array and nullable, index-aligned congestion arrays.
* [x] Added, removed, or invalid SP values retain their index and render as absent rather than borrowing another SP’s value.
* [x] Existing forecast map and mini-map consumers receive the same expanded cache shape.
* [x] Focused API tests, web typecheck, and frontend lint pass.
