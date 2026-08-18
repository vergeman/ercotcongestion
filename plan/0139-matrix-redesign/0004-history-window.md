# 0004 - history-window

Type: feat
Branch: `feat/0139-matrix-redesign/0004-history-window`
Source: `plan/0139-matrix-redesign/sprint-matrix-redesign.md`
Depends on: none. Optional — 0003 works on the existing 30-day series without it.

## Goal

Extend the trailing history series (currently 30 days) that backs the detail pane's sparkline /
whisker, IF it can be done without new precompute. Otherwise document the cap and the path.

## Context

* The trailing series is built in `api/analysis.py` by `_settled_mu_profile` (~line 509) and
  `_settled_node_profile` (~line 542), and surfaced on the Brief history fields
  (`settled_history`, `settled_history_p10..p90`).
* This is investigative: split out of 0003 so an uncertain data question never blocks the UI.

## Steps

1. [x] **Traced the window.** The literal `30` is not one constant but the same convention
   independently hardcoded at ~10 call sites across `api/analysis.py` (`range(1, 31)`,
   `timedelta(days=30)`, `range(30, 0, -1)` — top-constraints ~342/419, standouts ~1181-1208,
   top-nodes ~1304-1311, the climatology baseline `_trailing_settled_average`'s
   `range(1, 31)` at 609, etc.). `_settled_mu_profile`/`_settled_node_profile` (the plan's named
   entry points, now at 175/512) are the *single-day* fetch these all lean on; the actual
   trailing-window batching lives in `_windowed_mu_profiles`/`_windowed_node_profiles` (540/573,
   added in 0137), which already fetch the whole window in one round trip via a `days: int`
   parameter — so the plumbing to request a wider window already exists for the climatology path.
   Source depth (dev DB, checked directly): `ercot_dam_shadow_prices` 2023-12-13 → today (975
   distinct days), `ercot_dam_spp` 2025-01-01 → today (590 distinct days) — both far beyond 30,
   on TimescaleDB hypertables with chunk-exclusion on `interval_ts` (`EXPLAIN ANALYZE` on a
   90-day scan confirms a fast, chunk-excluded index scan, not a source/perf ceiling).
2. **Not implemented — no consumer to widen for.** The plan's step 2 says to "expose the longer
   series to the node endpoint `/analysis/node`" — but `/analysis/node` carries no
   `settled_history*` fields today, and 0003 (this sprint's actual Read-pane build) deliberately
   *dropped* history from the Matrix detail pane rather than deferring it to a wired-but-empty
   stub: Brief's `settled_history` arrays are keyed to Brief's own top-k rows, not the Matrix
   search index's full vocabulary, so there is no honest source for most Matrix selections
   without adding a new history field to `/analysis/node` first — a net-new endpoint capability,
   not a window-width parameter on an existing one. Building that capacity now, with nothing to
   call it and nothing to validate the shape against, would be exactly the kind of
   build-for-a-hypothetical this repo's conventions warn against. The STOP condition the plan
   anticipated was "needs new precompute"; the actual one hit here is "needs a new consumer
   first" — same outcome (leave 30 days), different cause.
3. **Extension path, for whoever adds a Matrix history consumer:** add a `settled_history*` field
   set to `AnalysisNodeResponse`/`AnalysisConstraintRow` (or a small dedicated history endpoint),
   backed by `_windowed_mu_profiles`/`_windowed_node_profiles` with an explicit `days` param
   (already plumbed, not hardcoded) rather than a new query path; keep every existing Brief call
   site's `range(1, 31)` / `timedelta(days=30)` literals untouched so nothing there moves.
4. Brief's default window/appearance is untouched — no code changed in this pass.

## Do NOT touch

* `web/` code, `/matrix/frame`, the Brief's existing history rendering.

## Acceptance

* [x] Either: a longer trailing window is available to the detail pane behind a param, with the
      Brief default unchanged — or: a written finding explains the cap and the extension path.
      (The latter: no cap on the data or the query: the source holds 590-975 days and the batched
      windowed-profile queries already take a `days` param; the reason nothing is exposed is that
      0003 has no history consumer to widen for, not a technical ceiling.)
* [x] No regression to the Brief history bars/whiskers — no code touched.
