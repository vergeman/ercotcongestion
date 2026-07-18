# 0093-0002 - runner: SF-only (drop bp scoring + panel)

Type: refactor
Branch: refactor/0093-0002-runner-sf-only

## Goal

* Make `compute.sf.runner` fit + persist only the SF matrix — remove the `bp`
  scoring, the `bp_ercot.npz` write, and the `--persist` / `--promote` `bp` DB path.
* Reduce `rolling_bp` to a window-walker that fires `on_refit_window` (where SF
  persistence happens) and no longer scores or returns a `bp` panel.

## Context

* The map consumes `implied_shift_factors` (+ geo + meta) only; the scored `bp` panel
  is written to disk and served nowhere (0093-0001 removed the last API reader).
* `compute/sf/rolling.py`'s scoring (`binding_proximity`, the `out` list + `concat`,
  the return value) exists only to produce `bp`. `eval.py` has its own scoring and
  does NOT import `rolling_bp`; this `rolling_bp` is called only by `runner.py`.
* `skip_window_starts` (added on 0092) STAYS — 0005 uses it. The `RefitWindow`
  payload and the warmup read-back logic stay.

## Approach

* Work in: `compute/sf/rolling.py`, `compute/sf/runner.py`, `compute/sf/metric.py`
  (delete), `compute/sf/tests/test_rolling_skip.py`.
* `rolling.py`: drop the score step and the `binding_proximity` import; `rolling_bp`
  walks windows, fires `on_refit_window`, and returns `None`. Keep window-walking,
  warmup, `skip_window_starts`, and `RefitWindow`.
* `runner.py`: remove `--persist`, `--promote`, `--layer`, the `bp_ercot.npz` write
  block, the "no bp rows produced" error path, and the imports of `copy_bp_rows`,
  `delete_run`, `set_current_pointer`. Keep `--persist-sf` and the SF/`sf_window_meta`
  persistence (still `delete_sf_run` + full rewrite here — 0005 makes it incremental).
  Rewrite the module docstring (drop the bp / `--persist` / `--promote` / npz sections).
* Delete `compute/sf/metric.py` (only `binding_proximity` lives there).
* `test_rolling_skip.py`: rewrite to assert on `on_refit_window` firings (which
  `window_start`s were fit) instead of the returned panel — skip semantics are
  unchanged, only the observable moves from the return value to the callback.
* Do NOT touch: `fit.py`, `eval.py`, `geo_persist.py`, `grouping.py`.

## Acceptance

* [ ] `runner --persist-sf` still writes `implied_shift_factors` + `sf_window_meta`;
  no `bp_ercot.npz`, no `implied_binding_proximity` writes.
* [ ] `--persist` / `--promote` / `--layer` no longer parse (argparse rejects them).
* [ ] `map_refresh_cronjob` steps 1 (SF), 2 (geo), 3 (eval) still run end-to-end.
* [ ] `grep -rn binding_proximity compute/sf` returns nothing (outside `legacy/` / `experiments/`).
* [ ] `pytest compute/sf` green (skip test reworked to the callback observable).
