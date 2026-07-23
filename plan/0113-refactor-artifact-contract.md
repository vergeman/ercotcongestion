# 0001 - run-artifact-contract

Type: refactor
Branch: refactor/0103-run-artifact-contract

## Goal

* Make `<run-id>` the canonical namespace for every persisted μ forecast and backtest artifact.
* Store each run's SF, μ, and forecast CSV/NPZ outputs beneath `compute/runs/<run-id>/` with stable, derived paths.
* Complete the compute runbook with the weekly scoreboard load and the existing live-grade behavior.

## Context

* SF artifacts already use `compute/runs/<run-id>/sf/`, and μ residual pools partly use `compute/runs/<run-id>/mu/`, but `mu_model`, `backfill_nodal`, and `load_scoreboard` still default to incompatible legacy files under `compute/mu/`.
* A forecast run (`mu-all-v1`) depends on, but is not the same version as, the independently refreshed SF map (`map-v1`); `--map-run-id` remains an explicit dependency rather than merging the two cadences into one identifier.
* `daily_forecast` already calls `grade_day` after publishing; the README omits that behavior and omits `load_scoreboard`, leaving the documented pipeline incomplete.
* Existing files under `compute/mu/` are untracked legacy artifacts and must remain usable through explicit path overrides during migration.

## Approach

* Work in: `compute/README.md`, `compute/runs/README.md`, `compute/mu/mu_model.py`, `compute/jobs/backfill_nodal.py`, `compute/jobs/load_scoreboard.py`, and their focused tests.
* Entry point / primary change: a shared run-artifact path convention rooted at `compute/runs/<run-id>/`.
* Define and document the canonical tree:

  ```text
  compute/runs/<run-id>/
    sf/
        diagnostics_*.json
        eval.csv
    mu/
        mu_weekly.csv
        mu_preds.npz
        spill/
    forecast/
        mu_bands_weekly.csv
        mu_nodal.npz
  ```

* Add `--run-id` to `compute.mu.mu_model`; when present, derive `mu/mu_weekly.csv` and `mu/mu_preds.npz` unless explicit `--out` / `--preds-out` overrides are supplied. Create parent directories before writing.
* Make `backfill_nodal --run-id` derive its residual-pool and score inputs from the same run, and derive its bands CSV and nodal NPZ outputs when callers do not override them. Preserve the current explicit-path and run-id-less modes for legacy/debug use.
* Make `load_scoreboard --run-id` default to that run's `mu/mu_weekly.csv` and `forecast/mu_bands_weekly.csv`; retain `--score` and `--bands` as explicit compatibility overrides.
* Update the runbook so every production artifact command is driven by `RUN_ID` and derived output paths rather than hand-built `ART_DIR` / legacy `/compute/mu` paths. Add the missing scoreboard-load step after historical backfill.
* Document that the daily job performs the normal `grade_day` call itself after a successful publish; include the standalone `grade_day --delivery-date auto --run-id ... --to-db` command only for retry/manual operation, not as a duplicate standard step.
* Do NOT touch: the SF fit math, forecast/scoreboard database schema, deployment schedules, or experimental and ablation artifact conventions beyond documenting that they require their own run IDs.

## Acceptance

* [ ] A single forecast `--run-id` resolves the μ weekly metrics, residual pool, bands CSV, and nodal NPZ to deterministic paths under `compute/runs/<run-id>/`; explicit output flags still override those paths.
* [ ] `mu_model`, `backfill_nodal`, and `load_scoreboard` no longer default to `/compute/mu/mu_*.{csv,npz}` when invoked with a run ID.
* [ ] The README presents an ordered map → μ pool → nodal backfill → scoreboard load → daily forecast pipeline, with `grade_day` accurately described as embedded in the daily forecast path and available for manual retry.
* [ ] Focused CLI/path-resolution tests cover default derivation, parent-directory creation, and legacy explicit-path compatibility; affected compute tests pass.
