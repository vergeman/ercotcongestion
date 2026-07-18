# 0094-0004 - delete compute/legacy/

Type: refactor
Branch: refactor/0094-0004-delete-legacy-compute

## Goal

* Delete `compute/legacy/` — the frozen pre-v3 compute (clustering, mapping, matrix,
  calibration, regimes, snapshot, `run_pipeline`, contingency/ptdf, …) — and its tests
  and docs, now that nothing produces or consumes its artifacts.

## Context

* After `0002`/`0003` nothing live reads the legacy artifacts (`congestion_matrices.npz`,
  scorecard/cluster npz) or the `served_run_dir` model those jobs fed.
* No live module imports `compute.legacy`: the only reference is a docstring comment in
  `compute/ercot/zones.py` ("… now frozen under `compute.legacy`") — update the comment,
  not an import.
* `congestion_matrices.npz` and the scorecard/cluster artifacts are built ONLY under
  `compute/legacy/` — deleting it removes dead producers.

## Approach

* Work in: `compute/legacy/` (delete tree), `compute/ercot/zones.py` (docstring),
  `docs/` (any legacy-map docs), `db/migrations/` (see below).
* Delete the `compute/legacy/` directory wholesale, including its `tests/` and the
  `test_snapshot.py` / `test_binding_proximity.py` at its root.
* Update the `compute/ercot/zones.py` docstring reference so it no longer points at a
  deleted module.
* Audit `db/migrations/` for tables used ONLY by the legacy pipeline (e.g. snapshot /
  clustering / matrix persistence — `07_snapshots.sql`, `16..18` congestion-metrics,
  clustering tables). Do NOT edit historical migrations; if any such table is confirmed
  dead, drop it in a new forward migration — but scope that carefully and only for
  tables with zero live readers. List candidates in the PR; default to leaving tables
  untouched unless clearly dead.
* Do NOT touch: `compute/sf`, `compute/mu`, `compute/ercot` (except the one docstring),
  `compute/experiments` unless a submodule imports `compute.legacy`.

## Acceptance

* [ ] `compute/legacy/` gone; `grep -rn "compute\.legacy\|import legacy" --include=*.py .`
  returns nothing.
* [ ] `python -c "import compute.sf.runner, compute.mu.propagate, api.main"` (or the repo's
  import-smoke) succeeds.
* [ ] The map + forecast cronjobs and `pytest` (full suite) are green.
* [ ] Any dead-table drops (if included) apply clean with `IF EXISTS` and have no live readers.
