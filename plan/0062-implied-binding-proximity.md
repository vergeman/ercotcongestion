# 0062 - implied-binding-proximity

Type: feat
Branch: feat/0062-implied-binding-proximity

## Goal

* Promote the `compute/experiments/implied_binding_proximity/` prototype
  into a first-class compute module that reads the ingested NP4-191-CD
  shadow prices (plan 0061) and the DAM SPP congestion decomposition, and
  writes per-hour `bp_ercot[sp]` for the map's ERCOT layer.
* Add a `--refit-days` CLI flag (default 7, matching the doc's weekly
  cadence), R² diagnostics, and a kept/dropped-constraints report.
* Wire the module into `compute/run_pipeline.py` as a new stage so it
  runs alongside the model-side `binding_proximity`.

## Context

* Prototype: `compute/experiments/implied_binding_proximity/ercot_binding_proximity.py`
  — CSV in / CSV out, hard-coded ridge, daily refit, no diagnostics. Doc:
  `docs/implied_binding_proximity.md`.
* Method (recap): fit `C ≈ −M·SFᵀ` with ridge on a rolling window; per hour,
  `bp_ercot[sp] = max_{c binding} |SF_implied[c, sp]|`.
* Reference chosen: `system_lambda` (ERCOT NP4-523-CD published λ). This is
  the distributed-slack convention — implied SFs are directly comparable to
  the model-side distributed-slack PTDFs from plan 0057.
* Known bias: DAM SPP feed does not publish MCL at SP granularity, so the
  input `congestion = LMP − system_lambda` is `MCC + MCL`. Losses appear as
  an R² ceiling and a mild systematic bias for far-from-load SPs. Accepted;
  documented under Known Limitations.
* Depends on plan 0061 (NP4-191-CD ingest) being merged.

## Approach

* Work in: `compute/implied_binding_proximity/` (new package),
  `compute/run_pipeline.py`, `docs/implied_binding_proximity.md`.
* Entry point / primary change: new `compute/implied_binding_proximity/runner.py`
  with `python -m compute.implied_binding_proximity.runner` CLI, mirroring
  the `compute/clustering/runner.py` shape used by the pipeline.

* **Module layout** — `compute/implied_binding_proximity/`:
  * `__init__.py`
  * `panels.py` — DB readers (Postgres, not CSV):
    * `load_shadow_prices(conn, start, end) -> pd.DataFrame` — pivot
      `ercot_dam_shadow_prices` to `(hours × key)` where
      `key = constraint_name + "|" + contingency_name`. Assert-unique per
      `(interval_ts, key)` before pivoting (surface the sum-vs-first
      ambiguity from the prototype).
    * `load_congestion_panel(conn, start, end, ref_method="system_lambda")
      -> pd.DataFrame` — pull SP-level congestion under the given ref
      method from wherever the existing pipeline already writes it (see
      `compute/matrix.py` / `compute/congestion/`); return `(hours × SP)`.
  * `fit.py` — ridge solve, promoted from the prototype:
    * `implied_shift_factors(M, C, lam, min_hours, standardize=True)`.
    * Add optional column-wise standardization on `M` before ridge so a
      fixed `λ` doesn't shrink small-μ constraints disproportionately
      (documented gap in the eval). Rescale coefficients back before
      returning.
  * `metric.py`:
    * `binding_proximity(M, SF) -> pd.DataFrame` — unchanged shape from
      the prototype; use vectorized `np.where(A[:, :, None], S[None, :, :],
      -np.inf).max(axis=1)` instead of the Python loop.
  * `rolling.py`:
    * `rolling_bp(con, spc, window_days, refit_days) -> pd.DataFrame` —
      refit every `refit_days`, score all days between refits with the
      most recent SF matrix. `refit_days=1` reproduces the prototype's
      daily behavior; default 7.
  * `diagnostics.py`:
    * Per-refit-window: overall R² on the fitted rows, per-SP R²,
      kept-constraint list with binding-hour counts, and the
      dropped-below-`min_hours` list. Write to `runs/<run_id>/ibp/
      diagnostics_<window_start>.json`.
  * `runner.py` — CLI:
    * `--run-id` (required, matches other stages).
    * `--start`, `--end` (default: pull from `--run-id`'s dates file).
    * `--window-days` (default 60), `--refit-days` (default 7),
      `--min-binding-hours` (default 10), `--ridge-lambda` (default 1e-2),
      `--ref-method` (default `system_lambda`).
    * Writes long-format Parquet `runs/<run_id>/ibp/bp_ercot.parquet`
      keyed `(interval_ts, settlement_point, bp_ercot)`, plus the
      per-window JSON diagnostics above.

* **Pipeline wiring** — `compute/run_pipeline.py`:
  * Add `"implied_binding_proximity"` to `STAGES`, placed after
    `matrix` (needs the congestion panel already computed by matrix) and
    before `clustering` (independent of it, but earlier keeps failure
    localized).
  * Extend `_stage_cmd` with an `implied_binding_proximity` branch:
    ```
    python -m compute.implied_binding_proximity.runner
        --run-id <run_id>
        [--window-days ...] [--refit-days ...] [--ref-method ...]
    ```
    Forward `--window-days`, `--refit-days`, `--ridge-lambda`,
    `--ref-method` from new orchestrator flags with sensible defaults.
  * Extend `_stage_outputs` to point at
    `runs/<run_id>/ibp/bp_ercot.parquet`.
  * Skip-completed behavior comes for free via existing `_run_stage`.

* **Doc cleanups** — `docs/implied_binding_proximity.md`:
  * Drop the "sub-1.0 near-binding gradient from non-binding rows"
    language in Methodology(4). NP4-191 publishes binding rows only; the
    metric simplifies to `max |SF|` over the binding set. Reflect that.
  * Add a Known Limitations bullet: `congestion = LMP − system_lambda`
    absorbs MCL; expect an R² ceiling below 1 and a small systematic bias
    for far-from-load SPs. No public SP-level MCL feed exists.
  * Update the "re-fit weekly" statement to reference the new
    `--refit-days` flag (default 7).
  * Add a short "Diagnostics" section documenting the emitted JSON.

* **Retire the prototype** —
  `compute/experiments/implied_binding_proximity/ercot_binding_proximity.py`:
  * After the promoted module has parity on the 2025-07-23 sample day,
    delete the experiment script and the two experiment-local CSVs
    (`2025-07-23.csv`, `dam_congestion_all_sp_2025-07-23.csv`, `SP.csv`,
    `bp_ercot.csv`) — they are frozen snapshots superseded by the DB feed.
    Keep the directory only if it still holds a useful README.

* Do NOT touch: the model-side `binding_proximity` (`compute/snapshot.py`,
  `compute/congestion/metrics.py`). The two layers are computed
  independently and only compared downstream on the frontend.

## Acceptance

* [x] `python -m compute.implied_binding_proximity.runner --run-id <id>
  --start 2025-05-24 --end 2025-07-23 --refit-days 7` completes without
  error and writes `runs/<id>/ibp/bp_ercot.npz` plus per-window
  diagnostic JSONs.
* [x] On the 2025-07-23 sample day, the top-|SF| SPs for
  `15060__B|SW_LVLT5` include Lamesa Solar, Alpine BESS, Gun Mountain,
  and Russek (all West Texas) — same as the doc's sanity check, now
  reproduced from DB inputs.
* [x] Per-refit-window overall R² is emitted and rises materially above
  the prototype's single-day 24-obs value (targeting R² > 0.5 on a
  full 60-day window; note the MCL residual bias in the diagnostic
  README rather than treating a sub-1 R² as failure).
* [x] Kept-constraint list JSON includes each surviving constraint's
  `binding_hours` count; dropped list includes constraints filtered by
  `--min-binding-hours`.
* [x] `python -m compute.run_pipeline --run-id <id>` runs the new stage
  in order between `matrix` and `clustering`; a re-run with existing
  output skips it.
* [x] `docs/implied_binding_proximity.md` no longer references the
  Value/Limit loading gradient, references `--refit-days` for cadence,
  and calls out the MCL residual bias.
* [x] `compute/experiments/implied_binding_proximity/` prototype set as demoted
  once parity check passes.
