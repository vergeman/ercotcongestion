# 0024 - pipeline-orchestrator

Type: feat
Branch: feat/pipeline-orchestrator
Status: done (npz round-trip vs legacy-test-persist not directly comparable — legacy was 11 ts, current reference_dates.json has 20 ts; npz is structurally correct)

## Goal

* Ship `compute/run_pipeline.py` — single composition layer chaining `congestion → ercot → matrix → clustering` via subprocess of the existing stage CLIs.
* Per-run `meta.json` with `run_id`, git sha, dates-file SHA-256, per-stage `status`/`elapsed_s`.
* Missing-snapshot guard against `bus_snapshots` before launching congestion; `--skip-completed` (default true) and `--force` for re-runs; `--records-output {gz,json,none}` propagated end-to-end with `none` deleting per-record JSONs after matrix exits ok.

## Context

* 0023 made every stage `--run-id`-aware; the orchestrator is the pure composition layer that wires them together.
* Subprocess composition is deliberately cheap — refactoring stage scripts into importable libraries is deferred.
* Phase 4 (validation framework) will consume `compute/runs/<run_id>/` triples; the orchestrator is what produces a complete, matched triple from one CLI invocation.

## Approach

* Work in: `compute/run_pipeline.py` (new). No further changes to stage scripts.
* CLI:

```
python -m compute.run_pipeline \
    --run-id <name> \
    --dates-file compute/sample_specs/reference_dates.json \
    [--ref-methods hub_avg,system_lambda_kkt,...] \
    [--algos hierarchical_corr,kmeans_vec,pca_kmeans] \
    [--ks 4,6,8,10,12,16] \
    [--records-output {gz,json,none}]  # default gz
    [--skip-completed]                 # default true
    [--force]                          # rerun everything
```

* Behavior:
  - Mkdir `compute/runs/<run_id>/`; copy the dates file into it; write `meta.json` with `run_id`, `created_at`, `git_sha`, `dates_file_sha256`, and a per-stage block (`status`, `elapsed_s`, optional `traceback`).
  - Pre-flight: query `bus_snapshots` for every timestamp in the dates file; if any missing, print the list + suggested `write_snapshots.py --start --end` and exit non-zero **without** launching congestion (no auto-ingest).
  - Run each stage as `python -m compute.<stage>` with `--run-id <name>` and (where relevant) `--records-output <mode>`. Skip a stage when `--skip-completed` and its primary output exists; print `skip: <stage> already complete`. On non-zero exit: capture stderr into the stage's `meta.json` block, mark `status="failed"`, stop.
  - When `--records-output none`: after the matrix stage exits ok, delete `compute/runs/<run_id>/congestion/{model_results,ercot_results}.json*` (the npz carries forward).
  - Final line: print the run directory and a one-line `du -sh` summary.
* Do NOT touch: any stage CLI, any import chain, any module under `compute/{congestion,clustering,matrix}.py`.

## Acceptance

* [x] `python -m compute.run_pipeline --run-id repro-test-persist --dates-file compute/sample_specs/reference_dates.json` produces a `compute/runs/repro-test-persist/` tree.
* [x] `meta.json` contains `run_id`, `git_sha`, `dates_file_sha256`, and per-stage `{status: "ok", elapsed_s: <float>}` for all four stages.
* [x] The orchestrator's matrix npz round-trips against `compute/runs/legacy-test-persist/matrix/congestion_matrices.npz` (matrix shapes + per-ref non-null masks match).
* [x] Re-running with the same `--run-id` is a no-op in under 2 s; every stage logs `skip: <stage> already complete`.
* [x] `--force` reruns everything (no skips).
* [x] Dates file with a timestamp absent from `bus_snapshots` → orchestrator prints the missing timestamp and exits non-zero **before** any subprocess launches.
* [x] `--records-output json` produces uncompressed `.json` per-record files.
* [x] `--records-output none` deletes `compute/runs/<run_id>/congestion/*.json*` after matrix completes; `ls runs/<run_id>/congestion/` shows no `.json[.gz]` files.
* [x] Stage failure: traceback is captured in the stage's `meta.json` block and downstream stages do not run.
