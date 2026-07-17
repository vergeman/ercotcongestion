# 0013 - forecast-day

Type: feat
Branch: feat/0013-forecast-day

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add `compute/mu/forecast_day.py` — the daily fit-then-predict job that, at/after DAM close on D−1, produces the forecast for delivery day D: nodal P10/P50/P90 + point and the per-day SF+μ artifact, written to Postgres, pointer flipped last (spec §2, §3, §6).
* Give `propagate_window` a forward/no-Y path: for a delivery day with no realized congestion yet, take the score hours from D's calendar, omit `Y`, and return `metrics = None` while still producing the panel + SF+μ artifact (spec §3.2).
* Add the `--delivery-date {tomorrow|YYYY-MM-DD}` / `--to-db` CLI (the daily run and the single-day backfill on the identical path) and a **two-sided production leakage test** that is a merge blocker (spec §5, §7 backfill).

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase2b-forecast-day.md` — §3 (two stages + orchestration sketch), §4 (`run_id` = model version, not day), §5 (cutoff discipline — the load-bearing risk), §6 (persist + self-owned pointer), §8 (failure modes), §9 (verification). Depends on **0012** (`predict_day`), **0010** (`forecast_nodal`/`forecast_current`, `nodal_to_db`, `upsert_pointer`), **0011** (`build_sf_mu_artifact`, `save/load_sf_mu`); do all three first.
* This job reads **live inputs**, so it does *not* inherit the backtest's built-in honesty (the backtest replays `mu_preds.npz`, already walk-forward). Every covariate must be pinned at DAM close via the existing `_dam_close_expr`/`history_cutoff` reads (`features.py` `:144`,`:161`,`:177`,`:193`,`:466`) — the SF fit window ends at `history_cutoff(D)` and never touches an interval ≥ D (spec §5). Leakage here is "the single easiest way to fabricate skill."
* `propagate_window` (`compute/mu/propagate.py:484`) today derives `hours = M_score ∩ C_score` and computes `Y` from realized congestion `C` — **neither exists for a forward D**. The spec's "unchanged except `end=D+1` and `Y` omitted" (§3.2) is the intent; the code needs an explicit forward branch (hours from the delivery-day calendar, `Y`/metrics skipped). Do not fabricate a `C` for D.
* This feature **owns its pointer** (`forecast_current[ercot]`, 0010): pointer flip is the last step, after rows land, so a reader never sees a half-written day. No `compute/promote.py`, no symlink tree (spec §6).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `compute/mu/forecast_day.py` (new), `compute/mu/propagate.py` (forward path on `propagate_window`), reusing 0010/0011 write helpers unchanged.
* **`propagate_window` forward path**: add a way to run with no realized outcome — e.g. `Y_available=False` or `hours` supplied by the caller. When forward: `hours` = the 24 delivery-day intervals of D (from the calendar / `wp`, not `M_score ∩ C_score`); skip the `Y = C_score.loc[hours, SF.columns]` read; return `row=None` (no `band_metrics`). The SF fit window `[D−WINDOW_DAYS, D)` and the `want_panel`/`want_sf_mu` tees stay exactly as today. `sf_coverage` is computed from `M_fit`/`M_score` where available, else `NaN` — do not let a missing `C` crash the panel.
* **`forecast_day(conn, D, *, run_id, train_days, arms=("lag","geo","wx"))`** — the §3 sketch:
  * Stage 1: `panel = features.build_panel(conn, ... D)` at DAM-close vintage; `wp = predict_day(panel, D)` (0012).
  * Stage 2: `M = load_shadow_prices(...)`, `C = load_congestion_panel(...)` over `[D−WINDOW_DAYS, D)` (fit only; no D rows); `eps = residual_pool(...)` (fixed pool, panel spec §7); `_, panel_out, SF, E_mu = propagate_window(s=D, end=D+1d, M=M, C=C, wp=wp, eps=eps, want_panel=True, want_sf_mu=True)` in forward mode; `sf_mu = build_sf_mu_artifact(SF, E_mu)` (0011).
  * Persist + publish: `nodal_to_db(...run_id, delivery_date=D)`, `write_sf_artifact(...)` (0011 `save_sf_mu` / bytea), then `upsert_pointer(conn, "ercot", run_id)` **last** (0010).
* **`run_id` = model version, not day** (spec §4): passed as a CLI arg (e.g. `mu-all-v1`); each daily run appends a new `delivery_date` under the same `run_id`; the pointer moves only when config changes. Write the bump policy into a short `run_id` docstring/comment (spec §10 open choice) so the scoreboard never splices two non-comparable models.
* **Cutoff discipline** (spec §5): every read goes through the DAM-close-vintage expressions already in `features.py`; do **not** hand-roll a "latest row" query. Assert the SF fit touches no interval ≥ D.
* **Failure modes** (spec §8): missing covariate vintage → **fail loudly, leave prior pointer intact**, no degraded forecast; empty `implied_shift_factors` → fail (a mapless forecast is not the product); degenerate all-zero μ head → assert non-flat before publishing; re-run of D → idempotent replace (0010 semantics), pointer unchanged if `run_id` unchanged; novel constraints → predict what's coverable + emit novelty (not an error).
* **CLI** `python -m compute.mu.forecast_day --delivery-date {tomorrow|YYYY-MM-DD} --run-id … --to-db`: `tomorrow` for the daily tick, an explicit date for single-day backfill/gap-fill on the identical path (spec §7 backfill). Run log: a line per stage + a coverage/novelty summary (spec §2, §7).
* Do NOT touch: the k8s CronJob yaml (that is 0014), `api/` endpoints (Phase 2 serving), `walk_forward`/`predict_day` internals (0012), the 0010/0011 write helpers' signatures, `compute/promote.py` / legacy pointer.

## Commits

<!-- Grouped so forecast_day runs end-to-end and the leakage test blocks a merge at branch end. -->

* **Commit A — `feat(propagate): propagate_window forward/no-Y path`**
  * `propagate.py` — hours from the delivery-day calendar, `Y`/metrics skipped, panel + SF+μ still teed; backtest path (`want_panel=False`, realized `Y`) byte-identical.
* **Commit B — `feat(mu): forecast_day two-stage job (fit → propagate → panel)`**
  * `forecast_day.py` — `forecast_day(conn, D, run_id, ...)` wiring `predict_day` → forward `propagate_window` → `build_sf_mu_artifact`; in-memory, no writes yet.
* **Commit C — `feat(mu): forecast_day persist + publish (self-owned pointer)`**
  * `forecast_day.py` — `nodal_to_db` + `write_sf_artifact` then `upsert_pointer` last; idempotent per `(run_id, D)`; `run_id` bump-policy note.
* **Commit D — `feat(mu): forecast_day CLI --delivery-date/--to-db + backfill`**
  * `forecast_day.py` — `--delivery-date {tomorrow|YYYY-MM-DD}` on the identical path; per-stage + coverage/novelty run log.
* **Commit E — `feat(mu): forecast_day failure modes (fail-loud, keep prior pointer)`**
  * `forecast_day.py` — missing-vintage / empty-SF / degenerate-μ guards; prior pointer intact on failure.
* **Commit F — `test(mu): production leakage (two-sided) + backtest reconciliation`**
  * `compute/mu/tests/` — **leakage (merge blocker, spec §5):** forcing any input's vintage past DAM close changes the output; the honest path uses no interval ≥ D. **Reconciliation (spec §9):** `forecast_day(D)` for a historic D inside the validated backtest, inputs pinned at DAM close, matches the backtest's nodal panel for D to tolerance. **Idempotency/atomicity:** D run twice → identical rows + one pointer; a reader mid-run sees old-or-new, never partial.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `propagate_window` forward mode produces the panel + SF+μ for a day with no realized `C` (hours from the calendar, `row=None`); the backtest path with realized `Y` is byte-identical to pre-change.
* [ ] `forecast_day(conn, D, run_id=…)` writes `forecast_nodal` (24 h × ~1k SP, `point` and `p50` both populated), `forecast_sf_artifact`, and flips `forecast_current[ercot]` **last**; never writes realized `Y` or driver rows (spec §2).
* [ ] **Leakage (blocker):** the two-sided test passes — pushing any input past DAM close changes the output, and the honest path touches no interval ≥ D (spec §5).
* [ ] **Reconciliation:** for a historic D inside the validated backtest, the forward panel matches the walk-forward panel for D to tolerance (spec §9).
* [ ] **Idempotency + atomicity:** running D twice yields identical rows and one pointer; pointer flips only after rows land (spec §6, §9).
* [ ] `--delivery-date YYYY-MM-DD` backfills a single historic day on the identical path under the same `run_id`; missing-vintage / empty-SF / all-zero-μ each fail loudly with the prior pointer intact (spec §7, §8).
* [ ] `pytest` green; `api/`, the CronJob yaml, and the 0010/0011 write helpers untouched.
