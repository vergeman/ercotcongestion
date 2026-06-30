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

* [ ] `extract_dates.py --per-regime 30` regenerates `reference_dates_120.json` deterministically.
* [ ] `compute/sample_specs/reference_dates_120.json` committed; 120 timestamps, 30 per regime.
* [ ] `python -m compute.run_pipeline --run-id v1-120 --dates-file …reference_dates_120.json` completes end-to-end.
* [ ] `compute/runs/v1-120/meta.json` shows all four stages `status="ok"`; total wall < 15 min.
* [ ] `pd.read_json(compute/runs/v1-120/clustering/summary.json)["rows"]` loads as a DataFrame with the documented columns.
* [ ] Spot-check: one (ref, algo, K) cell's GeoJSON renders in `geopandas` and labels look spatially coherent.
* [ ] `du -sh compute/runs/v1-120/congestion/` ≤ 10 MB; `du -sh compute/runs/v1-120/` ≤ 25 MB.
