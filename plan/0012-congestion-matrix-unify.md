# 0012 - congestion-matrix-unify

Type: feat
Branch: feat/0012-congestion-matrix-unify

## Goal

* Add `congestion_matrix.py` driver that joins OPF + ERCOT congestion on `(regime, ts)` and writes one analysis JSON.
* Implement `pca_variance_explained`, `pairwise_corr_distribution`, `split_half_cluster_stability` in `congestion.py`.
* Add `spearman_rank_agreement`, `distributional_agreement`, and `aggregate_to_zones` in `congestion.py`.
* Expose `ercot_congestion_snapshot.compute_records(timestamps_by_regime) -> list[dict]` for in-process use.
* Persist `bus_loads: {bus_id: load_MW}` on each OK record of `congestion_snapshot.py`.

## Context

* 0011 left two parallel snapshot pipelines (model OPF JSON; ERCOT DAM JSON) sharing `compute_congestion`, plus 3 stub diagnostics.
* Phase 2 close-out requires picking a reference method via model-vs-ERCOT agreement — needs joint matrices and stats.
* OPF is slow (min/chunk) with its own retry; ERCOT compute is cheap. Keep OPF as a separate producer; matrix consumes its file and runs ERCOT in-process.
* Working outline calls for load-weighted bus→zone aggregation, so model JSON must carry per-bus load.

## Approach

* Work in: `compute/experiments/congestion_calculation/`
* `congestion.py`:
  * `pca_variance_explained(C, n_components=10)` → `{explained_variance_ratio, cumulative, top_pc_loadings}`. Drop NaN buses; log count.
  * `pairwise_corr_distribution(C, n_bins=20)` → `{mean, median, std, q:{p5,p25,p50,p75,p95}, histogram:{edges,counts}}`. Pairwise-complete.
  * `split_half_cluster_stability(C, k=10, n_splits=5, seed=0)` → `{per_split_ari, mean_ari, std_ari}`. K-means + ARI on random temporal halves.
  * `spearman_rank_agreement(C_m, C_e, keys)` → `{per_hour_rho, summary:{mean,std,frac_positive}}`. Hourly rank correlation across `keys`.
  * `distributional_agreement(C_m, C_e, keys)` → per key `{ks_stat, ks_p, wasserstein, model_summary, ercot_summary}`.
  * `aggregate_to_zones(C, bus_zone, bus_weight)` → `(zone × hour)` load-weighted-mean matrix.
* `congestion_snapshot.py`: add `bus_loads` (from existing `loads_per_bus`) to each OK record. No other changes.
* `ercot_congestion_snapshot.py`: extract per-record compute into `compute_records(timestamps_by_regime) -> list[dict]`; have the CLI call it and write the JSON; return the SP→zone map and SP load weights alongside records (or via a sibling getter) so matrix can reuse.
* New `congestion_matrix.py`:
  * CLI: `--model-results PATH` (required), `--run-id` (default: from filename), `--ref-methods` (default all 6), `--k`, `--n-splits`.
  * Steps: load model JSON → filter `status=='ok'` → call `compute_records` for that `(regime, ts)` set → intersect on `(regime, ts)` → per ref_method build `C_bus` per source → run per-source structural diagnostics → build `C_zone` per source via `aggregate_to_zones` (model uses `bus_ercot_weather_load_zones.csv` + mean per-record `bus_loads`; ERCOT reuses snapshot's SP→zone + SP weights) → cross-source `spearman` + `distributional` on hubs (5 shared) and zones (8 weather) → write `congestion_matrix_<run_id>.json` with `meta: {n_records_model, n_records_ercot, n_common, dates_summary}` and per-ref-method `{model, ercot, cross_hubs, cross_zones}`.
* Do NOT touch: OPF solve path, DB schemas, dates-file format. Do NOT have `congestion_matrix.py` invoke the OPF.

## Acceptance

* [ ] `python compute/experiments/congestion_calculation/congestion_matrix.py --model-results compute/experiments/congestion_calculation/congestion_results_matrix-smoke.json` writes `congestion_matrix_matrix-smoke.json`.
* [ ] Output has per-ref-method blocks for all 6 methods, each with `model`, `ercot`, `cross_hubs`, `cross_zones`.
* [ ] `meta.n_common` ≤ min(`n_records_model`, `n_records_ercot`); cross-source stats restricted to that intersection.
* [ ] `explained_variance_ratio` sums ≤ 1, monotone-decreasing; ARI ∈ [-1, 1]; ρ ∈ [-1, 1]; KS p ∈ [0, 1].
* [ ] Re-run `ercot_congestion_snapshot.py` standalone with the same `--run-id` as 0011 → JSON value-equivalent to pre-refactor (no behavior change).
* [ ] Each new OK record from `congestion_snapshot.py` contains a `bus_loads` dict; existing fields unchanged.
* [ ] Spot-check each new `congestion.py` function on a fabricated 10-bus × 20-hour matrix in REPL before full run.
