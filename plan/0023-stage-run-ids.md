# 0023 - stage-run-ids

Type: feat
Branch: feat/stage-run-ids

## Goal

* Thread `--run-id` through every stage CLI so each stage can derive its inputs/outputs from `compute/runs/<run_id>/<stage>/`.
* Default per-record congestion outputs to gzip (`.json.gz`, ~10× smaller); matrix loader transparently handles both `.json` and `.json.gz`.
* Keep explicit-path flags working for ad-hoc/debug use — `--run-id` is additive.

## Context

* 0022 left every stage as a first-class module under `compute/`, but each CLI still requires the user to thread paths between stages by hand.
* At 11 snapshots per-record JSON is ~6.4 MB; at 120 ~70 MB; at 500 ~320 MB. Gzip is the cheapest default that handles the scale-up curve without changing inspection tooling (`zcat`, `pd.read_json` both handle `.json.gz`).
* 0024 (orchestrator) is pure composition; this branch must land first so the orchestrator just chains `--run-id` through subprocess calls.

## Approach

* Work in: `compute/congestion/{snapshot_runner.py,ercot_runner.py}`, `compute/matrix.py`, `compute/clustering/runner.py`.
* Five commits, each chains to the previous commit's output via `--run-id repro-11`.

**3a — gzip writers + transparent reader**
* `compute/congestion/snapshot_runner.py` and `compute/congestion/ercot_runner.py`: per-record writers open via `gzip.open()` when output extension is `.json.gz`; uncompressed when `.json`.
* `compute/matrix.py`: loader sniffs `.json` vs `.json.gz` and opens accordingly.
* Add `--records-output {gz,json}` flag to both congestion runners (default `gz`).

**3b — `compute/congestion/snapshot_runner.py --run-id`**
* When `--run-id <name>` is set and no explicit `--output` given, write to `compute/runs/<name>/congestion/model_results.json.gz` (or `.json` when `--records-output json`).
* Mkdir-p the output dir.

**3c — `compute/congestion/ercot_runner.py --run-id`**
* Same shape as 3b: defaults to `compute/runs/<name>/congestion/ercot_results.json.gz`.

**3d — `compute/matrix.py --run-id`**
* When `--run-id <name>` is set: derive `--model-results` from `compute/runs/<name>/congestion/model_results.json[.gz]` (prefer `.json.gz`, fall back to `.json`); write outputs to `compute/runs/<name>/matrix/{congestion_matrices.npz,matrix_summary.json}`.
* Explicit `--model-results` still wins when given.

**3e — `compute/clustering/runner.py --run-id`**
* When `--run-id <name>` is set: derive `--matrices` from `compute/runs/<name>/matrix/congestion_matrices.npz`; write to `compute/runs/<name>/clustering/`.
* Remove the inner `runs/<name>/` nesting the script used to create (the unified tree replaces it).

* Do NOT touch: `compute/snapshot.py`, `compute/write_snapshots.py`, or any module outside the four stage CLIs. Do NOT remove explicit-path flags.

## Acceptance

* [x] Each stage CLI accepts `--run-id`; output paths derive correctly under `compute/runs/<run_id>/<stage>/`.
* [x] Default per-record outputs are `.json.gz`; `--records-output json` emits uncompressed `.json`.
* [x] `compute/matrix.py` transparently loads either `.json` or `.json.gz` (verify by feeding it each).
* [x] Explicit-path flags (`--output`, `--model-results`, `--matrices`, `--out-dir`) still work with no `--run-id` set.
* [ ] Stage-by-stage chain on `--run-id repro-11` lands artifacts in `compute/runs/repro-11/{congestion,matrix,clustering}/` and reproduces the legacy npz from `compute/runs/legacy-test-persist/matrix/congestion_matrices.npz` (matrix shapes + per-ref non-null masks match). — pending Docker smoke
* [x] `compute/clustering/runner.py` no longer creates an inner `runs/<name>/` directory.
