# 0025 - sample-expansion-120

Type: feat
Branch: feat/sample-expansion-120

## Goal

* Bump the regime-balanced sampler's per-regime target from the current value to 30 (4 regimes × 30 = 120 snapshots) via a CLI flag.
* Generate and commit `compute/sample_specs/reference_dates_120.json`.
* Run the orchestrator end-to-end at 120 snapshots; verify all stages exit ok within the runtime budget and the artifact footprint matches projections.

## Context

* The 11-snapshot smoke is too small to stress the pipeline; 120 is ~6× scale, still completes in minutes, and matches the existing regime-balanced sampler's shape (4 regimes).
* Phase 4 (validation framework) is the next sprint and consumes the full per-run tree this branch produces — `v1-120` is the canonical input.
* 0024 (orchestrator) already supports the full end-to-end run; this branch only adds the sample and validates at scale.

## Approach

* Work in: `compute/sample_specs/extract_dates.py`, `compute/sample_specs/reference_dates_120.json` (new).
* Add a `--per-regime` CLI flag to `extract_dates.py` with default 30. The existing sampling logic stays unchanged.
* Generate `compute/sample_specs/reference_dates_120.json` and commit it.
* Run the full pipeline:

```
python -m compute.run_pipeline \
    --run-id v1-120 \
    --dates-file compute/sample_specs/reference_dates_120.json
```

* Expected footprint (per phase4 outline §6): per-record outputs ~7 MB compressed, matrix npz ~10 MB, clustering ~3–5 MB → total ~20 MB.
* Expected runtime: congestion ~3–4 min, matrix ~30 s, clustering sweep (4 ref × 5 algos × 6 Ks = 120 cells) ~5–8 min; total wall < 15 min (under the 10-minute clustering budget from 0020).
* Do NOT touch: the sampling algorithm itself, any stage CLI, or the orchestrator.

## Acceptance

* [x] `extract_dates.py --per-regime 30` regenerates `reference_dates_120.json` deterministically.
* [x] `compute/sample_specs/reference_dates_120.json` committed; 120 timestamps, 30 per regime.
* [x] `python -m compute.run_pipeline --run-id v1-120 --dates-file …reference_dates_120.json` completes end-to-end.
* [x] `compute/runs/v1-120/meta.json` shows all four stages `status="ok"`. **Wall ~59 min, not <15 min** — plan estimate was ~10× optimistic (per-chunk HiGHS solve ~75–90 s × 20 chunks). Deferred to a later optimization sprint.
* [x] `pd.read_json(compute/runs/v1-120/clustering/summary.json)["rows"]` loads as a DataFrame with the documented columns (192 rows: 8 refs × 4 algos × 6 Ks; 168 ok / 24 skip).
* [x] Spot-check: `zones_hub_avg_hierarchical_corr_k8.geojson` renders — 8 polygons, bounds match ERCOT footprint.
* [x] `du -sh compute/runs/v1-120/` = 25 M. **Congestion dir = 14 M (>10 MB budget)** — model_results.json.gz alone is 12 M at 120 snapshots × ~10 K buses × 8 refs. Budget miss, not a correctness issue.

## Notes

* Clustering invoked with `--algos hierarchical_corr,kmeans_vec,pca_kmeans,hybrid_geo` — `spectral_corr` excluded per instruction.
