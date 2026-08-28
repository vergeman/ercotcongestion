# 0173 - unify SF window loader

Type: refactor
Branch: refactor/0173-unify-sf-window-loader

## Goal

* Make `compute.sf_map.storage.maps.load_window_sf` the sole reader that reconstructs a persisted SF window.
* Preserve dense zero-filled matrices for serving and sparse `NaN` entries for geography derivation.

## Context

* `geography.persist._load_sf_window` duplicates the `implied_shift_factors` query and pivot in `storage.maps.load_window_sf`.
* Serving needs omitted threshold-sparsified values restored to zero; geography currently retains them as `NaN`, which its |SF|-weighted calculations treat as zero.
* `load_window_sf` is also used by forecast/backfill paths, so its existing dense default is public behavior.

## Approach

* Work in: `compute/sf_map/storage/maps.py`, `compute/sf_map/geography/persist.py`, and new focused tests under `compute/sf_map/tests/`.
* Add an explicit optional fill mode to `load_window_sf`, retaining the current dense zero-filled result by default and allowing the geography job to request its current sparse result.
* Import and call the shared loader from `geography.persist`; delete `_load_sf_window` and its duplicated query/pivot.
* Add fake-connection unit coverage proving the same persisted rows yield zero-filled serving output by default and `NaN` for omitted matrix cells in sparse mode.
* Add a geography-path test or assertion proving it requests sparse mode and still passes that matrix to `_window_geo` unchanged.
* Do NOT change SF SQL, thresholds, geography calculations, forecast safety gates, or any schema.

## Acceptance

* [x] `geography.persist` has no private SF-window SQL loader and reads through `storage.maps.load_window_sf`.
* [x] Default `load_window_sf` output remains dense, zero-filling threshold-omitted cells for existing serving/backfill callers.
* [x] Sparse loader mode preserves omitted cells as `NaN` for geography, including an empty-result case.
* [x] Focused `compute/sf_map` tests pass.
