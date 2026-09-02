# 0200 - unify-analysis-ranked-rows

Type: refactor
Branch: refactor/0200-unify-analysis-ranked-rows

## Goal

* Collapse the four ranked-table handlers in `api/services/analysis/panels.py` onto shared fetch + assembly helpers, keeping per-endpoint selection logic.
* Share the row schemas so the five `settled_history_pXX` fields and the row-field sets are declared once, not four times.
* Delete the seven empty `Unavailable` response subclasses.
* Emit byte-identical JSON on all four endpoints (no wire change).

## Context

* Top-constraints, top-nodes, constraint-standouts, and node-standouts each re-implement the same **fetch → select keys → assemble rows** pipeline; only selection differs.
* The settled-history percentile block is written 4× in `panels.py` (~22 `quantile` calls) and its five fields declared 4× across the row schemas; the rank idiom appears ~8×; the study-ESSP fetch and the ESSP representative-collapse each appear 2× (top-nodes + node-standouts); the dominant-driver calc appears 3×.
* The frontend reads these payloads by field name and types are hand-written (no OpenAPI codegen), so the refactor must be wire-identical but is free to rename/remove OpenAPI component names.
* All analysis routes have live consumers — this refactor removes no routes.

## Approach

* Work in: `api/services/analysis/panels.py`, `api/schemas/analysis.py`.

* **Schema bases (`schemas/analysis.py`):**
  * `SettledHistoryFields` — the 5 `settled_history_pXX` + `settled_history`; mixed into all four row models.
  * `ConstraintRowBase(SettledHistoryFields)` shared by `TopConstraintRow` and `StandoutRow` (base + `kind`, `forecast_history_median`, `forecast_history_days`, `chronic_bound_days`).
  * `NodeRowBase(SettledHistoryFields)` shared by `TopNodeRow` (+ `delta`, `coverage`) and `NodeStandoutRow` (+ `kind`, `forecast_history_median`, `forecast_history_days`).
  * `forecast_peak`/`forecast_hours` are optional on `ConstraintRowBase` so `StandoutRow` (which may omit them) fits; `TopConstraintRow` always fills them. Pydantic base-first field ordering means the serialized key order changes, but the acceptance and the frontend key by name, so the wire is unchanged.

* **Assembly helpers (`panels.py`):**
  * `settled_history_stats(values, *, nonzero_only, gate)` — the percentile whisker, replacing the 4 inline blocks. `nonzero_only` filters positive days (constraint whisker) vs. the full signed series (node whisker); `gate` nulls the percentiles when the series carries no signal, off only for top-nodes.
  * `ranked(series) -> (pd.Series, dict[str, int])` — stable descending sort + 1-based ranks, replacing the 6 Series-based rank idioms. (The 2 post-grouping rank dicts in top-nodes enumerate grouped lists, not a Series, and stay inline.)
  * `_resolve_or_unavailable(cur, run_id, delivery_date, horizon, unavailable_cls)` — the run/horizon preamble + soft-fail early return, shared by 8 handlers.
  * `_study_essp_groups(cur, hours)` and `_essp_canonical(universe, groups)` — the study-ESSP fetch and representative-collapse, previously duplicated across top-nodes and node-standouts.
  * `_dominant_driver(terms)` — the driver / driver-share calc (was 3×).

* **Model cleanup:** delete the seven `class X(NodeAnalysisUnavailableResponse): pass` subclasses; use `NodeAnalysisUnavailableResponse` directly in the unions and returns. `ContextUnavailableResponse` (kept) is passed to `_resolve_or_unavailable` via `unavailable_cls`.

* Keep the selection helpers as-is: `_standout_rows`, `_node_standout_rows`, `_settled_standout_keys`, `_settled_node_standout_keys`, `_joined_top_keys`.

* Do NOT touch: `compute/analysis/*`; `_compose_brief_details` thread fan-out; any selection threshold or ordering; `HeroUnavailableResponse`/`HeroUnavailableAtHorizonResponse`/`AnalysisEsspGroupsUnavailableResponse` (distinct fields). Remove no routes.

## Why the constraint row assembly is left inline in both handlers

The one abstraction the plan originally imagined — a shared `enrich_constraint_rows`
covering the top-constraints and standout rows — was tried and **backed out**. The two
paths differ in two real, byte-visible ways on the settled day:

* **Missing forecast column.** Top-constraints reads an absent forecast key as a zero
  profile → `forecast_peak = 0.0`; a standout row reads it as an empty series → `None`.
* **`settled_hours` null-gate.** Top-constraints gates on `settled_values is None`
  (missing key → `None`); a standout row gates on `settled.empty` (missing key on a
  settled day → `0`).

Folding those into one function meant a `variant="top"|"standout"` branch that just
re-forks the two behaviours — false DRY that reads worse than the two explicit blocks
and saves no lines. The blocks stay inline; both still share `settled_history_stats`
and `ranked`. Only genuinely identical logic (ESSP fetch/collapse, driver calc) was
extracted.

## Reality check on scope (revised after implementation)

The original acceptance targeted ~850–950 lines from ~1,680. **That was not achievable without a behaviour change and has been dropped.** Most of the duplication here is only **2-fold**, so factoring a block into a named helper removes two copies while adding one definition of comparable size — line-neutral, and only worth it when the two copies are byte-identical (ESSP collapse, driver calc), not when they need a flag to differ (constraint row assembly, left inline). The genuine line savings come from the blocks that were 4×/8× (the percentile whisker, the rank idiom) and the 8× preamble. Net outcome: `panels.py` ~1,540 lines from ~1,680 (~140 removed), all wire-identical.

## Follow-on: split `panels.py` into a package (physical, not logical)

The logical de-dup above is spent — the wire-identical rule caps it. The remaining
win is **code motion**: `panels.py` (~1,540 lines) becomes a `panels/` package so no
file exceeds ~one screen and the layout mirrors `routes/analysis/`. No logic changes,
same public surface (an `__init__` re-exports every current `panels.X`), so callers
and `brief.py`'s `panels.get_*` fan-out are untouched.

* **Modules:** `_common.py` (shared: `ranked`, `settled_history_stats`,
  `_resolve_or_unavailable`, the three tuning constants), `catalog.py`
  (node/settlement-points/constraints/essp), `grade.py` (grade + history),
  `constraints.py` (top-constraints + constraint standout helpers), `nodes.py`
  (node history/contributions + top-nodes), `context.py`, `standouts.py`.
* **Import graph is a clean DAG:** everything → `_common`; `context` → `constraints`;
  `standouts` → `constraints` + `nodes`. No cycles.
* **`get_standouts` (~290 lines) stays large** — it spans both domains and only
  *imports* the per-domain helpers; shrinking it is a separate logic change, out of scope.
* **Dead code dropped:** `_iso_z`/`_cursor`/`_verdicts` (and their `magnitude_verdict`/
  `render`/`build_hero` imports) were live only in `features/hero.py`, which keeps its
  own copies — removed here.
* **Net LOC ~+75** (per-file headers + `__init__` shim). A physical split shrinks
  files, not the total — the same lesson as above, from the other side.
* Two `_forecast_node_history` tests patch a dependency on the module and call the
  helper directly, so they now target the `panels.nodes` submodule.

## Acceptance

* [x] JSON for top-constraints, top-nodes, standouts, and grade byte-identical before/after across a settled past day, a forecast-only future day, and a no-artifact day (`json.dumps(sort_keys=True)`). Verified with a golden harness comparing original-HEAD code vs. refactored against the live DB, with Postgres parallelism disabled to defeat nondeterministic float aggregation (context/grade/grade-history/standouts/top-nodes/top-constraints × 3 phases, all identical).
* [x] The five `settled_history_pXX` fields declared once (`SettledHistoryFields`); the percentile block and the Series rank idiom each exist once in `panels.py`; the ESSP-collapse and driver calcs each exist once.
* [x] The seven empty `Unavailable` subclasses gone; `pytest api/tests` passes (161 passed, 3 skipped).
* [x] No route added or removed; `/openapi.json` still lists every current analysis path.
* [~] `panels.py` smaller: ~1,540 from ~1,680 (~140 lines). The original ~850–950 target was unrealistic (2-fold duplication factors line-neutral) and is withdrawn — the win is single-source-of-truth for the 4×/8× blocks, not LOC.
* [ ] Follow-on split: `panels.py` → `panels/` package (7 modules), largest file ~430 lines, pure code motion, `pytest api/tests` green, `/openapi.json` unchanged.
