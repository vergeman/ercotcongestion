# 0011 - congestion-matrix (model-side)

Type: feat
Branch: feat/0011-congestion-matrix
Status: done

## Goal (revised)

Build congestion matrix, infrastructure only: extend `congestion_snapshot.py`
with another reference method generator weighted; a per-record sanity block, and
a `--dates-file` CLI flag. Defer all structural diagnostics (PCA, pairwise-corr,
cluster stability) and reference-method selection when comparing model vs ERCOT.

## Added

### Model-based Synthetic Network

* `congestion.py`:
  * New method `gen_weighted = lmps − Σ(lmps × dispatch) / Σ(dispatch)`;
    `compute_congestion` gained a `dispatch` parameter.
  * `build_congestion_matrix(records, ref_method)` but used later
  * `pca_variance_explained`, `pairwise_corr_distribution`,
    `split_half_cluster_stability` present as `NotImplementedError` stubs —
    signatures preserved for later phase.
* `congestion_snapshot.py`:
  * `build_dispatch_per_bus` helper; dispatch passed into `compute_congestion`.
  * Old per-method `stats` block dropped; replaced with a `sanity` block
    (`simple_mean_centered`, `abs_max`, `n_extreme`).
  * `system_lambda_proxy` field renamed to `system_lambda`. Value unchanged
    (`lmps.median()`). Energy-balance dual was rejected because the load-
    weighted nodal-balance dual is mathematically identical to the existing
    `load_weighted` reference method.
  * `--dates-file PATH` CLI flag (accepts both flat-list and
    dict-of-regimes schemas).
  * Final summary line: `n_records / n_ok / n_missing / n_extreme_buses`.

### ERCOT Network Counterpart

* `ercot_congestion_snapshot.py`, sibling to `congestion_snapshot.py`, reuses
  `congestion.py::compute_congestion` unchanged.
* Tracked SPs = union of `settlement_points_geocoded.csv` (nodal SPs +
  `matched_capacity_mw`) + `hubs_lz_centroids.csv` (~1,107 SPs total; all
  present in `ercot_dam_spp`).
* Each SP assigned a weather zone via nearest-bus lookup against
  `bus_ercot_weather_load_zones.csv`. `load_weighted` per-SP weight =
  `zone_load / count(SPs in zone)`; `gen_weighted` per-SP weight =
  `matched_capacity_mw` (0 for hubs, LZs, and unmapped nodals).
* `system_lambda` is the real value from `dam_system_lambda` (not a proxy).
* DST: `DISTINCT ON (...) ORDER BY dst_flag ASC` per (ts, sp), mirroring
  `operating_data_adapter`.
* DB queries are batched per `--chunk-size` (default 24): one round-trip
  each for dam_spp / dam_system_lambda / load_by_zone per chunk — avoids
  N+1.
* Sanity block adds `n_sp_with_nameplate` so the size of the `gen_weighted`
  scalar's contributing subset is visible per-record (missing nameplate affects
  only `gen_weighted`; other 5 methods are untouched).
* Output: `ercot_congestion_results_<run_id>.json`; per-record schema mirrors
  0011 model side + `data_source: "dam"` and ERCOT sanity fields.
* Verified end-to-end via `--run-id ercot-smoke`: 11/20 records ok, 9 missing
  (un-backfilled 2025-summer + 2026 hours), 0 errors. Per ok hour: 6 methods ×
  ~960 SPs, ~80% with nameplate, real ERCOT `system_lambda`, 5/5 hubs present.

## Deferred

* PCA / pairwise-corr / cluster-stability — meaningful only model vs ERCOT.
* Reference-method selection.

## Verification

Ran end-to-end on `compute/profiling/reference_dates.json` via
`congestion_snapshot.py --run-id matrix-smoke`: 20/20 records ok, six methods in
each `congestion` block, summary line, and sanity tests present.
