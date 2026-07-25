# 0006 - matrix-discovery-controls

Type: feat
Branch: `feat/0118-matrix-feature/0006-matrix-discovery-controls`
Source: `plan/0118-matrix-feature/sprint-matrix.md`

## Goal

* Let advanced users find and retain relevant rows/columns without destabilizing the default view.
* Add explicit presets and bounds before considering an all-data virtualized view.
* Persist a small user-curated set of constraints and settlement points.

## Dependency and merge position

* Start after `0005-matrix-hover-metadata` is merged and the core interaction contract is stable.
* This is the final branch in the Matrix sprint.
* Treat all-data virtualization, path construction, alerts, daily briefs, stability analytics, and new modeling as later epics.

## Required context and invariants

* The full domain may exceed 100 constraints and thousands of settlement points.
* Re-ranking columns around each selected constraint would be disorienting.
* A raw numeric cutoff alone creates poor, irreproducible discovery views.
* The API remains bounded and server-controlled; discovery must never request an unbounded dense matrix.
* The default row/column order remains deterministic and frozen through playback/value-source changes.
* Pins augment the stable default universe and do not reorder its existing members.
* Selection should persist where possible. If filtered out, it remains explicit and can be revealed.
* Visible-row sums remain partial and must never be relabeled total nodal congestion.

## Approach

* Add search over constraint/contingency names and settlement-point names.
* Add row controls:
  * Top 30 forecast contribution (default);
  * Top 100;
  * pinned constraints; and
  * optional constraint-type filter.
* Add column presets:
  * Core exposures (default);
  * hubs/load zones or curated anchors where metadata supports them;
  * pinned settlement points; and
  * Core + pinned.
* Store bounded, versioned pin lists in local storage.
* Encode active presets/search/filter state in URL query parameters so the view is reproducible.
* Add “Reset view” and visible/total counts such as `30 of 143 constraints` and `40 of 1,126 settlement points`.
* Extend `/matrix/frame` only with bounded, indexed parameters needed by supported presets.
* Continue to enforce conservative server maxima and deterministic ordering.
* Preserve Matrix discovery state during playback; hour changes must not reset search, pins, filters, or selected universe.
* Clearly mark a selected item hidden by a filter and offer an action that reveals it.
* If measured usage justifies “All,” plan a separate branch for two-dimensional virtualization and/or server pagination.

## Out of scope

* An unbounded “All” request, custom spreadsheet engine, silent two-dimensional virtualization expansion, path construction, alerts, briefs, or stability analysis.

## Acceptance

* [ ] A user can locate a named constraint or SP without requesting an unbounded matrix.
* [ ] Pinned rows/columns remain visible through playback and value-source toggles.
* [ ] Default row/column ordering remains deterministic.
* [ ] URL state reproduces the selected presets/search/filter configuration.
* [ ] Pin persistence is bounded, versioned, and recoverable through Reset.
* [ ] Server limits prevent accidental multi-megabyte/unbounded responses.
* [ ] A filtered-out selection remains explicit and can be revealed.
* [ ] Filtering never relabels a partial visible-row sum as total congestion.
* [ ] Performance remains acceptable for every supported preset.

## Sprint-level verification

* [ ] Trace one fixture cell from stored artifact through API response, UI SF value, forecast contribution, DAM contribution, tooltip, and inspector.
* [ ] Verify the same timestamp survives Map ↔ Matrix navigation and browser back/forward.
* [ ] Verify a future date, published DAM date, partial match, and historical no-artifact date.
* [ ] Verify ordering across 24 hourly playback steps.
* [ ] Verify the UI never implies recovered SF is an official ERCOT factor.
* [ ] Verify all partial visible-row sums are labeled accurately.
* [ ] Verify the map Constraints tab and existing map behavior remain intact.
* [ ] Run backend tests and frontend build/checks in the canonical clean environment; document pre-existing environment failures separately.

## Merge boundary

Merge when bounded search, presets, filters, pins, URL reproducibility, and state persistence work at realistic scale and the full sprint verification passes.
