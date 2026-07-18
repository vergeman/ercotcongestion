# 0093-0003 - delete the standalone bp modules + persist helpers

Type: refactor
Branch: refactor/0093-0003-delete-bp-modules

## Goal

* Delete the now-orphaned `bp` code: `compute/sf/ingest.py`, the `bp` helpers in
  `compute/sf/persist.py`, and the IBP step of `compute/promote.py`.
* Leave the DB tables for 0004 and the zonal-symlink promote intact.

## Context

* After 0002 nothing writes `bp`: the runner is SF-only, so `ingest.py`, `promote`'s
  IBP block, and the persist `bp` helpers have no callers.
* `compute/promote.py` ALSO flips zonal/clustering symlinks (`scorecard.json`,
  `cluster_labels.npz`, top-level `current`) — KEEP that; remove only the IBP
  backfill + pointer flip.
* `check_ref_method` in `persist.py` is shared with the SF `--persist-sf` path —
  KEEP it. `DEFAULT_LAYER` is only a `bp`/promote concept — remove once its importers
  (runner in 0002, ingest deleted here, promote `--layer` removed here) are gone.

## Approach

* Work in: `compute/sf/ingest.py` (delete), `compute/promote.py`,
  `compute/sf/persist.py`, `docs/implied_binding_proximity.md`.
* Delete `compute/sf/ingest.py` entirely.
* `promote.py`: remove the `ingest_run` / `promote_layer` imports, the `--layer`
  arg, and the "IBP DB first" block (the `npz_path` / `ingest_run` / `promote_layer`
  branch, ~lines 127-171 and its `step3_writes`); keep `_cell_targets` symlink flips
  and the top-level `current` flip. Rewrite the docstring (drop the DB-served plane;
  it is now symlink-only).
* `persist.py`: delete `copy_bp_rows`, `delete_run`, `run_has_rows`,
  `set_current_pointer`, `get_current_pointer`, `promote_layer`, `DEFAULT_LAYER`.
  KEEP `check_ref_method`, `copy_sf_rows`, `delete_sf_run`, `write_window_meta`,
  `copy_constraint_geo_rows`, `delete_constraint_geo`, `update_eval_metrics`,
  `count_null_eval`. Rewrite the module docstring (SF + geo persistence, not `bp`).
* `docs/implied_binding_proximity.md`: delete, or move under a `docs/legacy/` archive
  — reviewer's call; note it in the PR.
* Check the `mu` tests that mention `implied_binding_proximity` (`test_propagate.py`,
  `test_forecast_day.py`) — they assert the mu path does NOT use the legacy pointer;
  confirm they still pass unchanged.
* Do NOT touch: DB migrations (0004), the zonal symlink logic in `promote.py`.

## Acceptance

* [ ] `compute/sf/ingest.py` gone; `python -m compute.promote --dry-run ...` still
  flips symlinks with no DB step.
* [ ] `grep -rn "copy_bp_rows\|promote_layer\|set_current_pointer\|get_current_pointer\|run_has_rows" compute/`
  returns nothing outside `legacy/`.
* [ ] Every touched module imports clean (no dangling references to deleted symbols).
* [ ] `pytest` green.
