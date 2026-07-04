# 0055 - run-pipeline-surgery

Type: refactor
Branch: refactor/0055-run-pipeline-surgery

## Goal

* Collapse `run_pipeline.py` to the analytical stages only: `matrix → correlation_map → basis_regression → cca → clustering → scorecard`.
* Remove OPF orchestration and per-record JSON options (`--records-output`, `_drop_per_record`, `_records_ext`, `_missing_snapshots` pre-flight against `bus_snapshots`).
* Rewrite the strengthened pre-flight to check `snapshot_meta.status='ok'` — the analytical pipeline's true precondition after [[0053-unified-opf-write-path]].

## Context

* [[0053-unified-opf-write-path]] made `write_snapshots.py` the single OPF entry point; `snapshot_runner.py` no longer exists.
* [[0054-matrix-db-driven]] made `matrix.py` a self-contained DB-reader; `ercot_runner.py` no longer exists as a stage.
* The `congestion` and `ercot` stages in `STAGES` are dead code once those branches land; `--records-output` is meaningless.
* Users now do OPF as a separate, parallelizable step (`docker compose run … write_snapshots.py`) and only invoke `run_pipeline.py` for the analytical layer.

## Approach

* Work in: `compute/run_pipeline.py`, `compute/README.md`.
* Entry point / primary change: `STAGES` tuple, `_stage_cmd`, `_stage_outputs`, `main()` pre-flight.

**Commit 1 — drop congestion/ercot stages, prune helpers**

* In `compute/run_pipeline.py`:
  * `STAGES = ("matrix", "correlation_map", "basis_regression", "cca", "clustering", "scorecard")`.
  * Remove `congestion` and `ercot` branches from `_stage_cmd` and `_stage_outputs`.
  * Delete `_records_ext`, `_drop_per_record`, the `--records-output` argparse entry, and the `if stage == "matrix" and args.records_output == "none":` block in `main()`.
  * Delete `_missing_snapshots` and `_ingest_hint` (the DB check moves into `matrix.py` per [[0054-matrix-db-driven]]; `run_pipeline.py` no longer connects to Postgres directly).
* Pass `--dates-file` through to `matrix` (that stage now needs it — previously only congestion/ercot did).

**Commit 2 — strengthen pre-flight**

* Replace the deleted `_missing_snapshots` check with a new pre-flight: connect to Postgres, query `SELECT interval_ts, status FROM snapshot_meta WHERE interval_ts = ANY(%s)`. Any ts missing or `status != 'ok'` → exit 3 with the ingest hint (`write_snapshots.py --start … --end …`).
* This is cheap (~1 query) and worth doing before spawning stage subprocesses even though `matrix.py` will re-check. Fail-fast at the orchestrator boundary matches the current UX.
* Alternative if preferred: fully delegate to matrix's pre-flight and drop the orchestrator-level check. Pick one; do not do both.

**Commit 3 — docs update**

* Rewrite `compute/README.md` §4 ("Run the analytical pipeline") to reflect the new stage list, removed flags, and the "OPF is a prerequisite, not a stage" framing.
* Update `compute/README.md` §"Debugging individual stages" — congestion + ERCOT entries deleted (already handled in [[0054-matrix-db-driven]] Commit 4 if it landed first; here confirm).
* Update the module docstring at the top of `run_pipeline.py` (the ordering comment, the `Usage::` block).

* Do NOT touch: mapping / clustering / scorecard code paths beyond the argparse plumbing.

## Acceptance

* [ ] `python -m compute.run_pipeline --run-id <id> --dates-file <path>` runs end-to-end with only the six analytical stages and produces the same `scorecard_<id>.json` shape as before.
* [ ] `python -m compute.run_pipeline --help` shows no `--records-output` flag.
* [ ] Requesting a run against dates with any `snapshot_meta.status != 'ok'` exits non-zero with a clear ingest hint before any stage subprocess spawns.
* [ ] `git grep -E 'records_output|drop_per_record|snapshot_runner|ercot_runner'` in `compute/run_pipeline.py` returns no hits.
* [ ] `--skip-completed` (default) still no-ops stages whose primary output exists under the same `--run-id`.
