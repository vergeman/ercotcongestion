# 0073 - add-kkt-perbus-zone-local-spp

Type: feat
Branch: feat/0073-add-zone-local-spp

## Goal

* Land `zone_local_spp` as an ERCOT-side reference price so `kkt_perbus × zone_local_spp` pairs are computable from a fresh `compute.matrix` run.
* Land `assign_load_zones()` + `LOAD_ZONES` in `compute/ercot/transforms.py` as the single canonical 4-way ERCOT load-zone helper (mirrors `assign_weather_zones`).
* Land `compute/mapping/compare_refs.py` + `compute/mapping/pairs/default.json` so future ref-pair sweeps don't need to re-derive the harness.

## Context

* `kkt_perbus` (model side) already lives on master — landed by 0071 fix (`compute/congestion/compute.py:41`, `compute/matrix.py:152`). This plan does **not** re-add it.
* Experiment `experiment/0072-zone-reference-price` also introduced `zone_local_kkt` (model-side zonal recentering of `kkt_perbus`). We are **not** taking that in; the target pair is `(kkt_perbus, zone_local_spp)`. Revisit if the compare-harness output later argues for it.
* `assign_load_zones()` is defined in the experiment branch's `transforms.py` and duplicated inside `compute/experiments/load_weighted_ablation/check_zone_a.py`; the experiment folder is out of scope, we only import the canonical copy.
* `pairs/default.json` in the experiment references `zone_local_kkt`; those rows will be dropped for this landing since the method is not being added.

## Approach

### Commit 1 — helper: `assign_load_zones()` + `LOAD_ZONES`

* Work in: `compute/ercot/transforms.py`
* Add `LOAD_ZONES = ('houston', 'north', 'south', 'west')` next to `WEATHER_ZONES`.
* Add `assign_load_zones(tracked)` verbatim from `experiment/0072-zone-reference-price:compute/ercot/transforms.py` (SP → nearest-bus → 4-way ERCOT load zone).
* Do NOT touch: `assign_weather_zones`, DB fetchers, `compute/experiments/*`.

### Commit 2 — method: register `zone_local_spp`

* Work in: `compute/congestion/compute.py`
* Append `"zone_local_spp"` to `METHODS` with the same doc block used on the experiment branch (ERCOT-only, filled outside `compute_congestion`, per-ts SPP minus zonal mean).
* Do NOT touch: `compute_congestion` internals, `kkt_perbus` docstring, or any other method.

### Commit 3 — `matrix.py`: fill `zone_local_spp` in `build_ercot_matrices`

* Work in: `compute/matrix.py`
* Import `LOAD_ZONES` and `assign_load_zones` alongside `assign_weather_zones`.
* In `build_ercot_matrices`, add the `want_zone_local_spp` block ported from the experiment: assign SP→load-zone once, then per-ts subtract the load-zone mean SPP from each SP's SPP into `ercot_C["zone_local_spp"]`. Hub SPs stay NaN by design.
* Extend `GUARDED_RUN_IDS` from `{"v1-annual"}` to `{"v1-annual", "v1-annual-kkt"}` and swap the guard branch to the set-based error message from the experiment.
* Do NOT touch: model-side `build_model_matrices` (kkt_perbus path is already correct on master), `_build_ref_vec`, or anything zone_local_kkt-shaped.

### Commit 4 — compare harness + default pairs

* Add `compute/mapping/compare_refs.py` from the experiment branch **as-is**.
* Add `compute/mapping/pairs/default.json` from the experiment branch, but drop the two entries that reference `zone_local_kkt` (`kkt_x_zone_local_spp`, `kkt_x_lambda`, and `load_weighted_x_load_weighted` stay; the two `zone_local_kkt` rows are removed).
* Do NOT touch: `correlation_map.py`, `scorecard.py`, `basis_regression.py`.

## Acceptance

Static (already verified by inspection):

* [x] `assign_load_zones` + `LOAD_ZONES` exported from `compute/ercot/transforms.py`.
* [x] `"zone_local_spp"` is the only new entry in `compute/congestion/compute.py:METHODS`.
* [x] `compute/matrix.py:GUARDED_RUN_IDS == {"v1-annual", "v1-annual-kkt"}` and the CLI guard uses the set with a set-based error message.
* [x] `build_ercot_matrices` computes `sp_to_load_zone` only when `enable_zone_local_spp` (`"zone_local_spp" in ref_methods`). Note: `assign_load_zones` runs a nearest-bus KNN over every tracked SP incl. the HB_*/LZ_* centroids, so hubs *do* get a load-zone label and *do* get filled (they are not NaN). If we want hubs excluded from `zone_local_spp` and/or the per-ts zone mean, that's a follow-up.
* [x] `compute/mapping/compare_refs.py` ported verbatim; imports resolve against master's `correlation_map`.
* [x] `compute/mapping/pairs/default.json` contains exactly 3 pairs — `kkt_x_lambda`, `kkt_x_zone_local_spp`, `load_weighted_x_load_weighted` — with no reference to `zone_local_kkt`.
* [x] No files under `compute/experiments/` are added or modified.

Runtime (docker compose stack, verified against `flat_dates_2025-01-03_2025-01-06.json`, 72 hrs):

* [x] `docker compose run --rm compute python -m compute.matrix --run-id smoke-0073 --dates-file /compute/sample_specs/flat_dates_2025-01-03_2025-01-06.json` writes `congestion_matrices.npz` with `zone_local_spp_ercot_C` populated (940 SPs × 72 hrs, 100% finite for non-hub rows; per-ts zonal-centered mean ≈ 0 across non-hub rows). Model-side `zone_local_spp_model_C` stays all-NaN as intended.
* [x] `docker compose run --rm compute python -m compute.mapping.compare_refs --run-id smoke-0073` produces `runs/smoke-0073/compare/compare.{csv,md}` with rows for the 3 default pairs; no reference to `zone_local_kkt`. Sample headline: `kkt × zone_local_spp` median corr 0.452, p90 0.667, distinct winners 44.
* [x] `--run-id v1-annual` and `--run-id v1-annual-kkt` both exit non-zero with the set-based guard message (`refusing to overwrite ship-state artifacts under --run-id='…' (guarded set: ['v1-annual', 'v1-annual-kkt'])`).
