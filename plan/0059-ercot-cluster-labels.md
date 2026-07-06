# 0059 - ercot-cluster-labels

Type: feat
Branch: feat/0059-ercot-cluster-labels

## Goal

* Attach `cluster_id` to each ERCOT settlement point in `/api/topology`, derived from the CM.1 correlation mapping.
* Render SPs colored by cluster in the right-hand ERCOT pane, matching the model pane.
* Preserve the current unlabeled fallback when the mapping or labels artifact is missing.

## Context

* Model buses already carry `cluster_id` via `_load_bus_cluster_labels` in `api/services/topology_builder.py`; SPs do not.
* `mapping_correlation_<run>.npz` already contains `sp_id`, `best_bus`, `best_corr` for all SPs — the SP↔cluster label is a lookup, not a new algorithm.
* Geographic `transfer_labels` (polygon containment) is diagnostic-only under CM.1/CM.2 — do not use it for this.
* Frontend `spTopology` in `web/src/App.tsx` already spreads SP properties into a bus-shaped feature; `GridMap` colors any feature with `cluster_id`. Rendering is mostly free once the payload carries the field.

## Approach

### Commit 1 — backend: SP cluster labels in topology

* Work in: `api/services/topology_builder.py`
* Add `_load_sp_cluster_labels() -> dict[str, int]`:
  * Load `mapping_correlation_<active_run>.npz` (path parallel to `_load_bus_cluster_labels`).
  * Load bus labels via existing `_load_bus_cluster_labels()`.
  * Return `{sp_id: bus_cluster[best_bus[sp_id]]}`; skip SPs whose `best_bus` isn't in the labels dict.
  * Soft-fail to `{}` if either file is missing (mirror the bus-label behavior).
* Thread the dict through `_settlement_points_feature_collection()` and add `cluster_id` + `best_corr` to each SP feature's `properties`.
* Extend `_cache_is_current()` to invalidate caches whose SP features lack `cluster_id`.
* Do NOT touch: `polygons.py`, `run_pipeline.py`, or the clustering sweep — this is a read-time derivation.

### Commit 2 — frontend: type + legend surface

* Work in: `web/src/api/types.ts`, `web/src/App.tsx`, `web/src/components/map/GridMap.tsx`
* Add `SPFeatureProperties { sp_id; sp_type; cluster_id?; best_corr? }` to `types.ts`; update the `settlement_points` shape in `App.tsx::spTopology` to use it (spread already forwards the fields — no logic change).
* In `GridMap.tsx`, verify SP layer's paint expression reads `cluster_id` the same way as the bus layer; add a null/`-1` branch so unlabeled SPs render neutral grey.
* Confirm the cluster legend / selection sync (`selectedClusterId`) highlights matching SPs in the right pane the same way it highlights buses in the left.
* Do NOT touch: validation panel, scorecard, or any API model besides the topology feature type.

## Acceptance

* [ ] `GET /api/topology` returns `settlement_points.features[i].properties.cluster_id` (int or null) and `best_corr` (float or null) for the active run.
* [ ] Deleting `TOPOLOGY_CACHE` and re-hitting the endpoint rebuilds the cache; an existing pre-schema cache is detected stale and rebuilt.
* [ ] With `mapping_correlation_<run>.npz` absent, SP features still serialize with `cluster_id: null` and the endpoint does not 500.
* [ ] In the UI, ERCOT SPs paint in the same palette as the model buses; selecting a cluster in the legend highlights members in both panes.
* [ ] Unlabeled SPs (missing from mapping, or `best_bus` not in labels) render in the neutral/unclustered style.
