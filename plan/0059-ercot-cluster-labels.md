# 0059 - ercot-cluster-labels

Type: feat
Branch: feat/0059-ercot-cluster-labels

## Goal

* Derive an ERCOT-side `cluster_id` per settlement point from the CM.1 mapping and expose it in `/api/topology`.
* Color SPs by cluster on the right-hand map pane, in sync with the left pane's Zones toggle and selection.

## Context

* Model buses already carry `cluster_id` via `_load_bus_cluster_labels`; SPs did not.
* `mapping_correlation_<run>.npz` already stores `sp_id → best_bus, best_corr` — the SP label is a lookup, not a new algorithm.
* Under CM.1/CM.2 the model→ERCOT translation is correlation-based, so geographic `transfer_labels` is not the right mechanism here.

## Approach

### Commit 1 — backend: SP cluster labels in topology

* `api/services/topology_builder.py`
* New `_load_sp_cluster_labels(bus_cluster) -> (sp_cluster, sp_corr)`: load `mapping_correlation_<run>.npz`, return `{sp: bus_cluster[best_bus[sp]]}` and `{sp: best_corr}`. Soft-fail to `{}` when the file is missing.
* `_settlement_points_feature_collection` now emits `cluster_id` and `best_corr` on every SP feature.
* `_cache_is_current` invalidates caches whose SP features lack `cluster_id`.
* Also fixed in this commit: `get_or_build_topology` now writes to `TOPOLOGY_CACHE.{pid}.{ns}.tmp` so concurrent rebuilds don't clobber each other's tmp; removed stray `print(tmp)`.

### Commit 2 — frontend: types + right-pane wiring

* `web/src/api/types.ts`: added `SPFeatureProperties { sp_id; sp_type; cluster_id?; best_corr? }`.
* `web/src/App.tsx`: typed `spTopology` with the new interface; wired the right-pane `<GridMap>` to share `showZones` and `selectedClusterId` with the main pane (they were hardcoded `false`/`null`, which was why the ERCOT map showed no cluster colors).
* `web/src/components/map/GridMap.tsx`: removed the `Z1..Zk` centroid symbol layer and its visibility effect from both panes.
* No changes needed to the paint/dim/legend paths — they iterate `topology.buses.features[i].properties.cluster_id` uniformly, and `clusterColor` already returns `CLUSTER_GRAY` for null.

## Acceptance

* [x] `GET /api/topology` returns `cluster_id` (int|null) and `best_corr` (float|null) on every `settlement_points.features[i].properties`.
* [x] With `mapping_correlation_<run>.npz` absent, SPs serialize with `cluster_id: null` and the endpoint does not 500.
* [x] Cache staleness detector rebuilds pre-0059 caches whose SP features lack `cluster_id`.
* [x] Two concurrent rebuilds no longer race each other's tmp file — each uses a unique path before `os.replace`.
* [x] With Zones on, the ERCOT pane paints SPs in the same palette as the model pane, and legend selection dims non-members on both sides.
* [x] Unlabeled SPs render neutral grey; no `Z1..Zk` centroid labels remain on either map.
* [x] `tsc --noEmit` clean.
