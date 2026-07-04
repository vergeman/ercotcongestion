# 0051 - reference-price-verification

Type: experiment
Branch: experiment/0051-reference-price-verification

## Goal

* Verify NP4-523-CD published λ falls in the sane range ($20–60/MWh, higher in stress events).
* Decide whether model `hub_avg` should average several nearby buses instead of taking the single nearest one.
* Validate `system_lambda_kkt` / `system_lambda_merit_order` across the full analysis window and compare against `load_weighted`, `gen_weighted`, `hub_avg`, `lmp_median`.

## Context

* Spun out from `plan/handoff-congestion.md` cleanup section.
* Code-level renames already landed in 0012 follow-on; this is the data/analysis side.
* `reference_prices` dict is now persisted per record, making cross-method comparison a direct read.

## Approach

* Work in: `compute/experiments/congestion_calculation/` and `docs/`.
* NP4-523-CD sanity: SQL over `dam_system_lambda` for the analysis window → distribution + flagged hours; cross-reference known stress dates.
* Hub-avg investigation: compare model `hub_avg` using (a) single-nearest bus vs (b) k-nearest mean (k = 3, 5) on a held-out snapshot set; pick whichever tracks ERCOT HB_BUSAVG SPP more closely.
* λ validation: across the full window, plot/correlate `lmp_median`, `load_weighted`, `gen_weighted`, `hub_avg`, `system_lambda_kkt`, `system_lambda_merit_order`; flag stressed hours; spot-check a handful of snapshots by hand.
* Update `docs/congestion_stats.md` methods section: replace multi-method-selection narrative with "approximations of the principled λ" framing.
* Do NOT touch: snapshot solve path, METHODS list, estimator implementations.

## Acceptance

* [x] Range/distribution check on NP4-523-CD written up (table + flagged outliers).
* [x] Decision recorded for hub_avg: keep nearest-bus or switch to k-nearest mean, with the comparison numbers.
* [x] Cross-method reference-price comparison table across the analysis window (mean, p5/p50/p95, pairwise corr).
* [x] `README.md` methods section updated with path-appropriate framing.
