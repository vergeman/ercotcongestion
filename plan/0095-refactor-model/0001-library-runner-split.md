# 0001 - library-runner-split

Type: refactor
Branch: refactor/0094-0001-library-runner-split

## Goal

* Extract the SF-projection math (`E_mu @ SF` → `NodalPanel`, `save_nodal`/`load_nodal`) out of `compute/mu/propagate.py` into a `compute/sf` module.
* Move the three runners (daily forecast, weekly map, nodal backfill) into a new `compute/jobs/` layer that imports the μ + SF libraries.
* Leave `compute/mu` and `compute/sf` as import-only libraries: no CLI `main`, no DB writes, no pointer flips.

## Context

* The SF calculator is already shared (`compute.sf.fit.implied_shift_factors`); the confusion is that runners live inside the library dirs and `propagate.py` mixes projection math with npz/DB/CLI orchestration.
* Frozen, leakage-tested code — the golden (`mu_bands_weekly.csv`) and `forecast_day` leakage/determinism tests are the guardrail; behavior must not change.
* Depends on `0092-map-revizualization/0092-sf-incremental-append` (map runner settles first). `0002-shared-sf-fit` (this dir) builds on this structure.

## Approach

* Work in: `compute/sf/project.py` (new), `compute/jobs/` (new), `compute/mu/propagate.py`, `compute/mu/forecast_day.py`, `compute/sf/runner.py`.
* Entry point / primary change: `compute/jobs/{daily_forecast,weekly_map,backfill_nodal}.py`.
* Move `propagate_window`'s panel/projection + `NodalPanel` + `save_nodal`/`load_nodal` into `compute/sf/project.py`; `predict_day`/`walk_forward` stay in `mu_model`.
* Move the CLIs: `forecast_day.py` → `compute/jobs/daily_forecast.py`; `sf/runner.py` → `compute/jobs/weekly_map.py`; `propagate.py`'s `--nodal-out`/`--to-db`/`--load-nodal-npz` + `walk()` → `compute/jobs/backfill_nodal.py`. DB writers (`nodal_to_db`, `persist_sf_mu_artifact`, `upsert_pointer`) move with them.
* Update cronjob `command:` paths (`forecast_cronjob.yml`, `map_refresh_cronjob.yml`) and `compute/README.md` runbook to the new module paths.
* Do NOT touch: the fit/projection math semantics; test assertions (only their import paths).

## Acceptance

* [ ] `compute/mu` and `compute/sf` contain no CLI `main` and no DB side effects (library-only).
* [ ] `compute/jobs/{daily_forecast,weekly_map,backfill_nodal}.py` own the CLIs and DB/pointer writes.
* [ ] Both cronjob YAMLs + README point at the new module paths and run.
* [ ] `mu_bands_weekly.csv` golden byte-identical; `forecast_day` leakage/determinism/reconciliation tests pass unchanged (import paths updated).
* [ ] `pytest` green.
