# 0068 - calibration-db-stream

Type: refactor
Branch: refactor/0068-calibration-db-stream

## Goal

* Elevate `hub_k_sweep` and `lambda_validation` from `compute/experiments/` to a first-class `compute/calibration/` package.
* Port `hub_k_sweep/sweep.py` and `lambda_validation/cross_method_compare.py` off `.json.gz` snapshots and onto streaming reads from `bus_snapshots` / `snapshot_meta` / `dam_system_lambda` / `ercot_dam_spp`.
* Preserve current outputs: same per-hub k-sweep table (so a k can still be picked by eye) and same NP4-523-CD range report / cross-method distribution + correlation tables.

## Context

* Legacy readers rely on `runs/<id>/congestion/{model,ercot}_results.json.gz`, but the writers (`snapshot_runner.py`, `ercot_runner.py`) were removed in PR #82 / #83; only the frozen `v1-120` / `v1-120-postfix` copies still exist.
* `compute/matrix.py:151-171` already streams `bus_snapshots` via a psycopg named cursor with `itersize=10_000` — reuse that pattern; do not re-invent chunking.
* Every field the scripts read is in the DB: per-bus LMP (`bus_snapshots.lmp`), per-method model refs and shed (`snapshot_meta.reference_prices`, `snapshot_meta.load_shed_mw`), ERCOT hub SPPs (`ercot_dam_spp`), and published NP4-523-CD (`dam_system_lambda`).
* `dam_lambda_range.py` and `lmp_mc_identity.py` are already DB-driven — moving them is a path/import change only.

## Approach

* Work in: `compute/calibration/` (new), `compute/experiments/hub_k_sweep/`, `compute/experiments/lambda_validation/`, `compute/README.md`.
* Entry point / primary change: `compute/calibration/hub_k_sweep/sweep.py` and `compute/calibration/lambda_validation/cross_method_compare.py`.

* Create `compute/calibration/__init__.py`, `compute/calibration/hub_k_sweep/__init__.py`, `compute/calibration/lambda_validation/__init__.py` and move (preserving the two subdirs):
  * `experiments/hub_k_sweep/sweep.py` → `calibration/hub_k_sweep/sweep.py`
  * `experiments/lambda_validation/dam_lambda_range.py` → `calibration/lambda_validation/dam_lambda_range.py`
  * `experiments/lambda_validation/cross_method_compare.py` → `calibration/lambda_validation/cross_method_compare.py`
  * `experiments/lambda_validation/lmp_mc_identity.py` → `calibration/lambda_validation/lmp_mc_identity.py`
* Delete `compute/experiments/hub_k_sweep/` and `compute/experiments/lambda_validation/` in their entirety once the moves land (keep the old `.md` reports next to their new script homes as `hub_k_sweep.md`, `cross_method.md`, `dam_lambda_range.md`). Leave the rest of `compute/experiments/` (notably `shed_canary/`) untouched.
* In `calibration/hub_k_sweep/sweep.py`:
  * Drop `--model-results` / `--ercot-results`. Add `--start` / `--end` (default: full analysis window) and optional `--dates-file` (JSON list of UTC ts) for parity with `run_pipeline`.
  * Fetch `ok` timestamps once: `SELECT interval_ts FROM snapshot_meta WHERE status='ok' AND interval_ts BETWEEN %s AND %s`.
  * Fetch ERCOT hub SPPs once: `SELECT interval_ts, settlement_point, spp FROM ercot_dam_spp WHERE interval_ts = ANY(%s) AND settlement_point = ANY(%s)` with `HUBS`.
  * Stream model LMPs with a named cursor (`itersize=10_000`) mirroring `matrix.py:151-171`; accumulate the k-nearest sum + count per `(ts, hub, k)` incrementally — never materialize per-ts `pd.Series`.
  * Delete `_reconstruct_lmps` and the `NETWORK_NC`/`HB_BUSAVG` reconstruction — `bus_snapshots.lmp` is already the raw LMP.
  * Keep `HUBS`, `K_VALUES`, `_stats`, `_hub_table_md`, and the "Summary (across all hubs)" table verbatim so the per-hub / per-k markdown is comparable for the same window.
  * Add a `_pick_k(aggregate)` helper: pick the smallest `k ∈ K_VALUES` that satisfies `aggregate_spikes[k] == 0` and `aggregate_neg[k] == 0` and `mean(|1 − med_ratio|) ≤ 0.05` (tie-break: lowest drift). Fall back to the k that minimises drift if no k clears the gate.
  * Emit a `## Recommended k` section at the top of the report showing the pick, the three gate values that drove it, and a one-line rationale ("smallest k with no spike / no negative and drift ≤ 5%" or "no k cleared the gate; showing lowest-drift").
  * Print the recommended `k=<value>` on stdout in addition to the "matched snapshots" line so the report can be consumed by other scripts / CI without parsing markdown.
* In `calibration/lambda_validation/cross_method_compare.py`:
  * Drop `--model-results` / `--ercot-results`. Add `--start` / `--end`.
  * `model_by_ts` = `SELECT interval_ts, reference_prices, load_shed_mw FROM snapshot_meta WHERE status='ok' AND interval_ts BETWEEN %s AND %s` (one round trip; `reference_prices` is jsonb).
  * `system_lambda` column comes from `dam_system_lambda.system_lambda` joined on `interval_ts` (replaces the old ERCOT-side `reference_prices["system_lambda"]`).
  * `shed_ts` derives from `load_shed_mw > 0` on the same rows — no separate ERCOT fetch.
  * Keep `MODEL_METHODS`, `ERCOT_METHOD`, `_dist_stats`, `_pairwise_corr`, `_delta_stats`, and `_render_md` unchanged.
* `calibration/lambda_validation/dam_lambda_range.py` and `calibration/lambda_validation/lmp_mc_identity.py`: move only. Update the module docstring `Usage:` blocks to `compute.calibration.lambda_validation.*` and the `DEFAULT_OUT` paths to `/compute/calibration/lambda_validation/*.md`.
* Update `compute/README.md` Section 2 ("Reference-price sanity checks"): swap the invocations to `python -m compute.calibration.hub_k_sweep.sweep --start ... --end ...` and `python -m compute.calibration.lambda_validation.cross_method_compare --start ... --end ...` (and `compute.calibration.lambda_validation.dam_lambda_range`), drop the `--model-results` / `--ercot-results` flags, and remove the "Requires an existing model run" note. Mention that the sweep now emits a recommended k on stdout / in the report header.
* Do NOT touch: `compute/experiments/shed_canary/` (separate concern, still uses the frozen v1-120 `.json.gz`), `compute/matrix.py`, `compute/write_snapshots.py`, `HUB_K_NEAREST` in `compute.congestion.metrics`, or any run under `compute/runs/`.

## Acceptance

* [ ] `compute/calibration/hub_k_sweep/sweep.py` and `compute/calibration/lambda_validation/{dam_lambda_range,cross_method_compare,lmp_mc_identity}.py` exist; `compute/experiments/hub_k_sweep/` and `compute/experiments/lambda_validation/` are gone; `compute/experiments/shed_canary/` is untouched.
* [ ] `grep -rn "model_results.json\|ercot_results.json" compute/calibration/` returns nothing.
* [ ] `python -m compute.calibration.hub_k_sweep.sweep --start 2025-01-01 --end 2025-01-08` completes without opening any file under `compute/runs/`, writes `compute/calibration/hub_k_sweep/hub_k_sweep.md` with the same per-hub / summary tables as today plus a `## Recommended k` section at the top; `matched snapshots:` matches `SELECT count(*) FROM snapshot_meta WHERE status='ok' AND interval_ts BETWEEN ...`.
* [ ] Sweep stdout ends with a `recommended k=<value>` line and the same value appears in `## Recommended k` in the report.
* [ ] `python -m compute.calibration.lambda_validation.cross_method_compare --start 2025-01-01 --end 2025-01-08` writes `cross_method.md` with the same section set (Distribution — all, Distribution — shed-clean, Pairwise Pearson — all, Pairwise Pearson — shed-clean, Delta vs merit_order, Notes) and column headers as the current `experiments/lambda_validation/cross_method.md`.
* [ ] `python -m compute.calibration.lambda_validation.dam_lambda_range` produces the existing NP4-523-CD range report unchanged (only `DEFAULT_OUT` path differs).
* [ ] `compute/README.md` Section 2 references `compute.calibration.*` module paths and no longer mentions `--model-results` / `--ercot-results`.
* [ ] `rg "compute\.experiments\.(hub_k_sweep|lambda_validation)"` returns nothing outside archived `.md` files.

