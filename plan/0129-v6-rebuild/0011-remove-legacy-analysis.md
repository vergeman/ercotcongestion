# 0129-0011 - remove-legacy-analysis

Type: refactor
Branch: refactor/0129-0011-remove-legacy-analysis
Depends on: `0009`, `0010`

## Goal

* Delete the precomputed-brief stack once the v6 panels have replaced every reader of it.
* Keep the primitives that outlive the blob.

## Context

* Runs **last**, after `0009`/`0010` ship and nothing reads the old surface. The
  remaining reader is the legacy `/analysis` route itself; remove it with the blob.
  Same discipline as `0094`: re-source first, delete second.
* The rebuild's premise is that the blob is the problem — precomputed and truncated at
  build time (top-5 nodes per constraint, 249 of ~5,800 SF cells; 33 of 1,024
  constraints above the serving floor). Every `partial` row in the prototype's
  data-status table traced back to it. Once the panels read queries, the blob has no job.
* This list is a **starting point to re-verify at the time**, not a manifest to execute
  on trust. Eight months of drift will have moved things.

## Approach

* Work in: `compute/analysis/`, `compute/jobs/`, `api/`, `db/migrations/`, `web/src/`
* Verify-then-delete, one reader at a time. `grep` for each symbol before removing it;
  if anything outside the old page still imports it, stop and re-source that caller
  first.
* **Delete (expected):**
  * `compute/analysis/assemble.py` (`build_brief`) and `compute/analysis/after_action.py`
    — both exist solely to fill the blob.
  * `compute/jobs/daily_brief.py`, `compute/jobs/backfill_briefs.py`, and the
    `_brief_latest` step in `compute/jobs/daily_forecast.py`.
  * `web/src/pages/AnalysisPage.tsx`, its `/analysis` route, and its legacy Brief
    client/types.
  * `api/analysis.py::get_brief` / `get_brief_latest`, and the `Brief*` types in
    `web/src/api/types.ts:463-710` plus their client wrappers in
    `web/src/api/client.ts:277,292`.
* **Keep — these outlive the blob:**
  * `compute/analysis/metadata.py::load_sp_metadata` — still the SP metadata provider,
    imported outside the brief path.
  * `compute/analysis/brief.py` primitives `nodal_congestion` and
    `cell_contributions` — `0003` routes these. Audit `pair_contributions` and
    `/analysis/path` for removal: source–sink pairs are no longer a v6 reader.
  * `compute/analysis/families.py` is **mixed**. Audit per function, not per file:
    `canonical_hubs`, `best_pair`, `sf_reach`, `split_constraint_key` and the coordinate
    dedupe at `:334` may all still have callers. Do not delete the module wholesale.
* After the writer is gone, add a **new forward migration** that drops
  `analysis_brief`. Do not delete historical migration 38: that cannot remove the
  table from an already deployed database.
* Keep the tests that cover surviving primitives; delete only those that test
  `build_brief` / `after_action` directly.
* Do NOT touch: `forecast_sf_artifact`, the fit, the scoreboard tables, or anything
  `0003` routes.

## Acceptance

* [ ] `grep -rn "build_brief\|analysis_brief\|get_brief"` over `compute/ api/ web/src` returns nothing outside the deletion itself.
* [ ] `/analysis` and `AnalysisPage.tsx` are gone; `/` remains the Brief entry point.
* [ ] `load_sp_metadata`, `nodal_congestion` and `cell_contributions` still exist and still have callers; `pair_contributions` and `/analysis/path` have either a remaining caller or are removed.
* [ ] The daily tick runs clean with `_brief_latest` removed, and the forecast still publishes.
* [ ] `compute/analysis/tests/` passes with only blob-specific tests removed.
* [ ] The new forward migration drops no table that a live job still writes to.
* [ ] `tsc --noEmit -p web/tsconfig.app.json` clean.
