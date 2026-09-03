# 0203 - consolidate-date-helpers

Type: refactor
Branch: refactor/0203-consolidate-date-helpers

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add `localize_ct(x)` to `compute/time.py` and route every `pd.Timestamp(x, tz="America/Chicago")` bound through it.
* Add `unique_days(index)` to `compute/time.py` and route every `M.index.normalize().unique()` day-index through it.
* Replace the two inline re-implementations of `delivery_date_of` with the existing helper.
* Retarget the two indirect `ERCOT_TZ` re-exports so panel modules import it from `compute.time` directly.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `compute/time.py` is already the shared CT-delivery-day module (15 non-test importers); this folds scattered duplicates into it.
* The raw `"America/Chicago"` string literal is copy-pasted at ~14 CLI-bound sites instead of using `ERCOT_TZ`; `M.index.normalize().unique()` is duplicated verbatim at 8 sites.
* Pure refactor — no behavior change. `normalize()` on a tz-aware index normalizes in that index's own tz (not forced to CT); `unique_days` must preserve that exactly. `localize_ct` must pass `None`/`NaT` through unchanged (several CLI sites feed `args.start=None`, currently yielding `NaT`).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `compute/time.py` (add helpers), then the call sites below.
* Entry point / primary change: two new functions in `compute/time.py`.

**Step 1 — add helpers to `compute/time.py`:**
* `localize_ct(x) -> pd.Timestamp`: `ts = pd.Timestamp(x)`; return `ts` unchanged when it is `NaT`; else `ts.tz_localize(ERCOT_TZ)` if naive, `ts.tz_convert(ERCOT_TZ)` if aware. Docstring: "Coerce a date/timestamp to the equivalent CT-zoned instant." Mirrors the tz-branch already inside `ct_day_bounds`.
* `unique_days(index) -> pd.DatetimeIndex`: `pd.DatetimeIndex(pd.Index(index).normalize().unique()).sort_values()`. Docstring must state it normalizes in the index's own tz (does not re-zone to CT).

**Step 2 — route bounds through `localize_ct`** (replace `pd.Timestamp(<x>, tz="America/Chicago")`):
* `compute/evaluation/mu.py:307-308`
* `compute/mu_forecast/model/backtest.py:245,255,257`
* `compute/jobs/backfill_nodal.py:250-251`
* `compute/sf_map/geography/derive.py:476-477`
* `compute/experiments/mu/feature_ablation.py:217-218`
* `compute/experiments/mu/outage_ablation.py:135-136`
* `compute/experiments/mu/rerank.py:223-224`
* `compute/probes/outage_feed.py:323-324` (the arg is `daily.index.min() - Timedelta(...)`, still naive → `localize_ct` handles it)

**Step 3 — route day-indexes through `unique_days`** (replace `pd.Index(M.index.normalize().unique()).sort_values()`):
* `compute/evaluation/sf.py:136,357`
* `compute/experiments/sf_out_of_window/common.py:49` and `:55` (the `[-1]` max-day)
* `compute/experiments/sf_out_of_window/sf_stability.py:49`
* `compute/experiments/sf/coverage.py:154,290`
* `compute/mu_forecast/model/scheduling.py:18-19` — this reads a MultiIndex level; pass `panel.index.get_level_values("interval_ts")` into `unique_days`.

**Step 4 — reuse `delivery_date_of`:**
* `compute/analysis/brief_grade.py:177-179`: `frame["delivery_date"] = delivery_date_of(frame["interval_ts"])` (module already imports from `compute.time`; add the name).
* `compute/probes/outage_feed.py:350-351` (`day_of`): swap the inline `.tz_convert(...).tz_localize(None).normalize()` for `delivery_day_of(M.index)` — confirm it returns the tz-naive CT midnight the `groupby` expects (it does).

**Step 5 — direct the ERCOT_TZ imports:**
* `compute/mu_forecast/panel/sources.py:10` and `compute/mu_forecast/panel/engineering.py:12` currently import `ERCOT_TZ` via `panel.availability`; change to `from compute.time import ERCOT_TZ` (keep the other names each imports from `availability`). `availability.py` itself already imports from `compute.time` — leave it.

* Do NOT touch: `compute/mu_forecast/model/scheduling.py` fold/chunk `DateOffset` math (DST-load-bearing); the SQL-string builders in `availability.py`/`sources.py`; `essp.py:68` and `runner.py:261` (target tz varies — out of scope for this pass).

## Commits

* `refactor(0203): add localize_ct and unique_days to compute.time` — Step 1 + unit tests in `compute/mu_forecast/tests/test_time.py` (naive/aware/NaT for `localize_ct`; tz-aware ordering + own-tz normalize for `unique_days`).
* `refactor(0203): route CT bounds through localize_ct` — Step 2.
* `refactor(0203): route day-indexes through unique_days` — Step 3.
* `refactor(0203): reuse delivery_date_of/delivery_day_of and direct ERCOT_TZ imports` — Steps 4 + 5.
* `fix(rerank): use shared screening metrics` — Restore the deleted metric-helper dependency through its shared replacement.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `grep -rn '"America/Chicago"' compute --include='*.py' | grep -v /tests/` returns only `compute/time.py` (plus the SQL builders in `availability.py`/`sources.py`, which pass `ERCOT_TZ`).
* [x] `grep -rn 'index.normalize().unique()' compute --include='*.py' | grep -v /tests/` returns nothing.
* [x] `localize_ct(None)` and `localize_ct(pd.NaT)` return `NaT`; `localize_ct("2026-07-01")` equals the pre-refactor `pd.Timestamp("2026-07-01", tz="America/Chicago")`.
* [x] `sources.py` and `engineering.py` import `ERCOT_TZ` from `compute.time`; no module imports it via `panel.availability`.
* [x] `pytest compute/mu_forecast/tests/test_time.py` passes, including the new cases.
* [x] Full `pytest compute` is green (no behavior change).
