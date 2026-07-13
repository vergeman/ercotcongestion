# λ cross-method comparison (0049 S4.3)

Sample: **120** snapshots from v1-120-postfix (model side, post-shed / post-k-nearest). Shed-tainted snapshots (Pass-1 `load_shed_mw > 0`): **119**; shed-clean subset: **1**. ERCOT `system_lambda` (NP4-523-CD) joined from the v1-120 ercot_results by ts.

`system_lambda_merit_order` is the fixed model reference — the exact copper-plate λ recovered by economic dispatch. Every other column is an approximation compared against it. `system_lambda` (NP4-523-CD) is the real ERCOT-published λ and the closest external validator we have.

The v1-120 sample is a summer-peak stress set, so essentially all snapshots hit shed and the shed-clean subset is not statistically meaningful in this window. It is reported anyway so the code is ready for the full-year re-backfill; interpret with sample size in mind.

## Distribution — all snapshots

| method | n | mean | std | min | p5 | p50 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `hub_avg` | 120 | 42.96 | 27.29 | 0.10 | 23.62 | 32.44 | 101.07 | 164.89 |
| `load_weighted` | 120 | 130.94 | 53.04 | 38.23 | 48.94 | 127.95 | 228.84 | 278.28 |
| `gen_weighted` | 120 | 55.61 | 16.91 | 19.11 | 34.69 | 53.06 | 92.65 | 114.29 |
| `lmp_median` | 120 | 36.23 | 17.43 | 0.30 | 28.28 | 29.06 | 72.91 | 127.59 |
| `system_lambda_kkt` | 119 | 114.18 | 201.66 | -77.92 | 2.02 | 26.36 | 382.62 | 1162.31 |
| `system_lambda_merit_order` | 117 | 28.45 | 2.66 | 0.00 | 28.55 | 28.55 | 29.02 | 29.02 |
| `system_lambda` | 93 | 38.60 | 37.03 | -23.86 | 13.03 | 29.22 | 93.74 | 293.64 |

## Pairwise Pearson correlation — all snapshots

| | `hub_avg` | `load_weighted` | `gen_weighted` | `lmp_median` | `system_lambda_kkt` | `system_lambda_merit_order` | `system_lambda` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `hub_avg` | 1.000 | 0.375 | 0.755 | 0.975 | 0.056 | 0.177 | 0.776 |
| `load_weighted` | 0.375 | 1.000 | 0.842 | 0.400 | 0.231 | 0.158 | 0.161 |
| `gen_weighted` | 0.755 | 0.842 | 1.000 | 0.776 | 0.173 | 0.218 | 0.498 |
| `lmp_median` | 0.975 | 0.400 | 0.776 | 1.000 | 0.041 | 0.223 | 0.818 |
| `system_lambda_kkt` | 0.056 | 0.231 | 0.173 | 0.041 | 1.000 | -0.122 | 0.057 |
| `system_lambda_merit_order` | 0.177 | 0.158 | 0.218 | 0.223 | -0.122 | 1.000 | 0.371 |
| `system_lambda` | 0.776 | 0.161 | 0.498 | 0.818 | 0.057 | 0.371 | 1.000 |

## Notes

* `simple_mean` is omitted — it is an unweighted `lmps.mean()`, the centering diagnostic used by `compute_congestion`, not a λ approximation.
* Model-side sample is the v1-120 canary window (post-shed-fix, post-k-nearest). Full-year re-backfill will re-run this table.
* `system_lambda` join drops any snapshot missing from the ERCOT side (n reported per method above).
