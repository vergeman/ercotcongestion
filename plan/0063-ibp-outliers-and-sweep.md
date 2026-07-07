# 0063 - ibp-outliers-and-sweep

Type: feat
Branch: feat/0063-ibp-outliers-and-sweep

## Goal

* Cap numerical outliers in `bp_ercot` from the implied-binding-proximity fit.
* Add a hyperparameter sweep script over `--window-days`, `--refit-days`, `--ridge-lambda`.
* Emit a compact per-sweep summary (mean R², n_kept, `bp_ercot` p95/max).

## Context

* Live run (`compute/runs/test0062`) produced `bp_ercot` p99 = 65 but max = 4673.06.
* Root cause: constraints with mostly-zero shadow prices in a window have a small column-std; standardization divides by it, then rescale inflates the coefficient. Metric is `max |SF|` per hour, so a single blown-up column dominates the row.
* Fits are cheap once panels are loaded; a small grid across `(window, refit, λ)` is tractable and needed before we promote a run to the frontend.

## Approach

### Part A — outlier handling

* Work in: `compute/implied_binding_proximity/fit.py`
* Entry point: `implied_shift_factors`
* Add a **std floor** at standardization:
  * New constant `STD_FLOOR = 1.0` (units: $/MWh — one binding hour at ~$1 std). Expose as CLI flag later if needed; hardcode for now.
  * Replace the current zero-std guard with `scale = np.maximum(scale, STD_FLOOR)` so both zero-variance and low-variance columns get the same treatment.
* Add a **post-fit `|SF|` cap**:
  * New constant `SF_ABS_CAP = 1.0` (physical: SFs are unitless in $[-1, 1]$; anything above is a numerical artifact).
  * After the rescale-back, `beta = np.clip(beta, -SF_ABS_CAP, SF_ABS_CAP)`.
  * Return the clipped count alongside the DataFrame (change signature to `(sf_df, n_clipped)` and update the single caller in `rolling.py`), or attach it as `sf_df.attrs["n_clipped"]` if simpler.
* Wire the clip count into diagnostics:
  * `compute/implied_binding_proximity/diagnostics.py::refit_diagnostics` adds a `n_sf_clipped` field.
  * Runner logs it per refit.
* Do NOT touch: `panels.py`, `metric.py`, `rolling.py` beyond the plumbing needed for the clip-count return.

### Part B — sweep script

* Work in: `compute/scripts/sweep_ibp.py` (new file). Use Python, not shell, so pandas can build the summary table.
* Entry point: `main()` with argparse for the grid definition and output path.
* Behavior:
  * Accept `--start`, `--end`, and comma-separated grids for `--window-days`, `--refit-days`, `--ridge-lambda` (defaults: `60`, `7,14`, `1e-3,1e-2,1e-1`).
  * For each combo, spawn `python -m compute.implied_binding_proximity.runner --run-id ibp_sweep_w{W}_r{R}_l{L} --start ... --end ... --window-days W --refit-days R --ridge-lambda L` via `subprocess.run`.
  * After all runs finish, walk each run's `runs/<id>/ibp/diagnostics_*.json` files and each run's `bp_ercot.npz`, computing per-run: `mean(r2_overall)`, `median(n_kept)`, `bp_ercot` p95, p99, max, and `n_sf_clipped` sum.
  * Print a `pandas.DataFrame` sorted by max desc (or write to CSV under `compute/scripts/ibp_sweep_summary.csv` if `--out` given).
* Reuse of loaded panels is out of scope — each runner invocation re-queries Postgres. It's slow but simple; revisit only if the grid gets large.
* Do NOT touch: `runner.py` beyond bug fixes. The script is a pure orchestrator over the existing CLI.

## Acceptance

* [ ] Re-running the test0062 range with the outlier fixes lands `bp_ercot.max() ≤ 1.0` (post-clip) and `p99` is not dramatically different from the pre-fix p99 (~65 — clipping shouldn't affect the well-conditioned bulk).
* [ ] Diagnostics JSON has `n_sf_clipped`; runner logs it.
* [ ] `python -m compute.scripts.sweep_ibp --start 2025-01-01 --end 2025-07-01` completes across the default grid and prints a summary table with the columns listed above.
* [ ] Each sweep row's `run_id` matches its runs/ output directory (grep-able).
