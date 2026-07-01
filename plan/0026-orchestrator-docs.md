# 0026 - orchestrator-docs

Type: docs
Branch: docs/orchestrator-readme

## Goal

* Update `compute/README.md` so `run_pipeline.py` is documented as the canonical entry point; per-stage scripts move to a "Debugging individual stages" section.

## Context

* By 0025 the orchestrator + per-run layout are validated at 120 snapshots; the README still reflects the pre-lift, per-stage-only workflow.

## Approach

* Work in: `compute/README.md`.
* `compute/README.md`:
  - New section "Running the pipeline": `python -m compute.run_pipeline --run-id <name> --dates-file …` as the canonical invocation. Reference `compute/runs/<run_id>/` tree.
  - New section "Debugging individual stages": brief examples for `compute.congestion.snapshot_runner`, `compute.congestion.ercot_runner`, `compute.matrix`, `compute.clustering.runner` with explicit-path flags. Note `--run-id` is also accepted on each.
  - Cross-link `compute/runs/README.md` for the per-run layout details.
* Do NOT touch: any code, any other plan, the per-run README written in 0021.

## Acceptance

* [x] `compute/README.md` has a "Running the pipeline" section that names `run_pipeline.py` as canonical.
* [x] `compute/README.md` has a "Debugging individual stages" section covering the four stage CLIs with both explicit-path and `--run-id` examples.
* [x] No code or stage CLI changes in this branch (`git diff --stat` shows only `*.md`).
