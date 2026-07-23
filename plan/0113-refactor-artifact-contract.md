# 0001 - run-artifact-contract

Type: refactor
Branch: refactor/0113-run-artifact-contract

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
* Define and document the canonical tree. **Two distinct run IDs, not one — the
  stage subdirs live under different runs.** The SF `sf/` artifacts belong to the
  *map* run (`<map-run-id>`, e.g. `map-v1`); the `mu/` + `forecast/` artifacts belong
  to the *forecast* run (`<run-id>`, e.g. `mu-all-v1`). They are versioned on separate
  cadences (map weekly, forecast daily) and joined only by `backfill_nodal
  --map-run-id`. No single run holds all three subdirs.

  ```text
  compute/runs/<map-run-id>/          # the SF MAP run (weekly; e.g. map-v1)
    sf/
        diagnostics_*.json            # compute.sf.eval: per-boundary fit diagnostics
        eval.csv                      # honest out-of-window eval

  compute/runs/<run-id>/              # the FORECAST run (daily model version; e.g. mu-all-v1)
    mu/
        mu_weekly.csv                 # mu_model --out: walk calibration metrics
        mu_score_weekly.csv           # compute.mu.score: per (week×source×regime) currencies
        mu_preds.npz                  # mu_model --preds-out: predictions / residual pool
        spill/
    forecast/
        mu_bands_weekly.csv           # backfill_nodal --out: P50 band metrics
        mu_nodal.npz                  # backfill_nodal --nodal-out: nodal P10/P50/P90 panel
  ```

  > **Why two run IDs and not one tree.** A single weekly SF map serves ~7 daily
  > forecasts, and either side can be re-versioned without the other — so the
  > forecast run cannot *own* the map's `sf/` dir. The forecast never reads `sf/`
  > off disk anyway: SF is DB-sourced at backfill/serve time, queried by
  > `map_run_id` (`resolve_sf_window`/`load_forecast_sf`), so `<map-run-id>` is the
  > key that joins two independently-keyed namespaces
  > (`implied_shift_factors[map-v1]` ↔ `forecast_nodal[mu-all-v1]`). The `sf/`
  > subdir holds only the map's diagnostics. This refactor does not merge the two
  > cadences into one identifier.

  > **`mu_weekly.csv` ≠ `mu_score_weekly.csv`.** They are two different files with
  > two different schemas: `mu_weekly.csv` is `mu_model`'s walk calibration
  > (`brier`/`ece`/`mae_mu_*`…), while `mu_score_weekly.csv` (from `compute.mu.score`,
  > out of this refactor's file scope) carries the score currencies
  > (`source`/`regime`/`pooled_r2`…) that `backfill_nodal`'s `r5` and
  > `load_scoreboard` consume. Both live under `mu/`; neither is the other.

* Add `--run-id` to `compute.mu.mu_model`; when present, derive `mu/mu_weekly.csv` and `mu/mu_preds.npz` unless explicit `--out` / `--preds-out` overrides are supplied (`resolve_output_paths`). Create parent directories before writing (`persist_outputs`).
* Make `backfill_nodal --run-id` derive, via `resolve_walk_paths`: the residual pool (`mu/mu_preds.npz`) and score input (`mu/mu_score_weekly.csv`), and — as OUTPUTS filled only under a run id — the bands CSV (`forecast/mu_bands_weekly.csv`) and nodal NPZ (`forecast/mu_nodal.npz`). Inputs also resolve run-id-less (legacy `compute/mu` bundle); run-id-less outputs stay opt-in (`None`). `--to-db` now needs `--run-id` (which derives `--nodal-out`) or an explicit `--nodal-out`. `--load-nodal-npz` derives nothing. Preserve the current explicit-path and run-id-less modes for legacy/debug use.
* Make `load_scoreboard --run-id` default `--score` to that run's `mu/mu_score_weekly.csv` (the score CSV — *not* `mu_weekly.csv`, which is the wrong schema) and `--bands` to `forecast/mu_bands_weekly.csv` (`resolve_board_paths`, reusing `backfill_nodal`'s helpers); retain `--score` and `--bands` as explicit compatibility overrides.
* Update the runbook so every production artifact command is driven by `RUN_ID` and derived output paths rather than hand-built `ART_DIR` / legacy `/compute/mu` paths. Add the missing scoreboard-load step after historical backfill. *(Discovered gap: the scoreboard load AND `backfill_nodal`'s `r5` both consume `mu_score_weekly.csv`, which nothing in the old runbook produced — so the `compute.mu.score` invocation is now documented in the μ step, with explicit derived paths since `score` has no `--run-id` and is out of this refactor's modify-scope.)*
* Document that the daily job performs the normal `grade_day` call itself after a successful publish; include the standalone `grade_day --delivery-date auto --run-id ... --to-db` command only for retry/manual operation, not as a duplicate standard step.
* Do NOT touch: the SF fit math, forecast/scoreboard database schema, deployment schedules, or experimental and ablation artifact conventions beyond documenting that they require their own run IDs.

## Acceptance

* [x] A single forecast `--run-id` resolves the μ weekly metrics, residual pool, bands CSV, and nodal NPZ to deterministic paths under `compute/runs/<run-id>/`; explicit output flags still override those paths.
* [x] `mu_model`, `backfill_nodal`, and `load_scoreboard` no longer default to `/compute/mu/mu_*.{csv,npz}` when invoked with a run ID.
* [x] The README presents an ordered map → μ pool → nodal backfill → scoreboard load → daily forecast pipeline, with `grade_day` accurately described as embedded in the daily forecast path and available for manual retry. *(compute/README.md steps 0–7; compute/runs/README.md tree extended with mu/ + forecast/)*
* [x] Focused CLI/path-resolution tests cover default derivation, parent-directory creation, and legacy explicit-path compatibility; affected compute tests pass. *(mu: `test_mu_model.py`; jobs: `test_backfill_nodal.py`, `test_load_scoreboard.py` — 33 new/covered, full mu+sf suite 237 passed / 1 skipped)*
