# 0050 - hub-lmp-k-nearest-mean

Type: fix
Branch: fix/0050-hub-lmp-k-nearest-mean

## Goal

* Replace single-nearest-bus hub LMP lookup with a k-nearest mean.
* Pick k via a full-year sweep against ERCOT HB_BUSAVG SPP and pin it in code.
* Cut HB_NORTH / HB_WEST outlier incidence vs the pre-fix baseline.

## Context

* Pre-fix `build_hub_lmps` took the single nearest synthetic bus per hub — one arbitrary sample from what ERCOT publishes as a hub average.
* On the v1-120 baseline that produced HB_NORTH spikes to $2116, HB_WEST negative on 38/93 non-shed snapshots, and a hub-level median-ratio drift of 1.29 vs ERCOT DAM SPP.
* `hub_avg` is a comparison baseline, not the headline model reference (`merit_order` is).

## Approach

* Work in: `compute/congestion/snapshot_runner.py`.
* Entry point / primary change: `build_hub_lmps` (lines 63–90).
* Replace `nearest = bus_ids[int(np.argmin(d2))]` with the mean over the k smallest `d2`; expose k as a module-level constant.
* Sweep k over the full-year window; correlate model `hub_avg` against ERCOT HB_BUSAVG SPP; pick the k that minimizes median-ratio drift AND spike incidence.
* Do NOT touch: `METHODS` list, estimator implementations, `hub_avg` consumers downstream.

## Acceptance

* [x] `build_hub_lmps` averages k-nearest buses; chosen k in a code constant and noted in `docs/congestion_stats.md`.
* [x] k-sweep comparison table (mean, p5/p50/p95, corr vs HB_BUSAVG, spike counts) committed under `docs/`.
* [x] HB_NORTH / HB_WEST outlier counts drop materially vs the pre-fix baseline; drop quantified in the sweep doc.
