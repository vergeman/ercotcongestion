# 0198 - Scrubber-scoped SF fit metadata

Type: fix
Branch: fix/0198-scrubber-scoped-sf-fit-metadata

## Goal

* Show OOS Accuracy, coverage, and SF Stability for the SF window behind the map day selected by the scrubber.
* Preserve the actual artifact/window provenance, including nearest-past artifact fallback.
* Stop using the newest `sf_window_meta` row as universal Map SidePanel metadata.

## Context

* `sf_window_meta` already stores `sf_oos_r2`, `coverage`, and `sf_stability` per map run and window; the map-refresh evaluation updates those fields.
* `/map/summary` calls `aggregate.meta()`, whose `common.resolve()` deliberately selects the newest window once at workspace load.
* Cursor-scoped `/map/exposures` and `/map/reach` already resolve the requested delivery day's SF+μ artifact for detail cards.
* The global SidePanel must not receive bootstrap `mapMeta`, whose latest-window semantics do not follow historical scrubs.

## Approach

* Work in: `api/services/map/common.py`, `api/services/map/aggregate.py`, `api/schemas/map.py`, `api/routes/map.py`, `web/src/api/map.ts`, `web/src/api/types.ts`, `web/src/workspaces/MapWorkspace.tsx`, and `web/src/components/panels/SidePanel.tsx`.
* Commit 1 — Extract a shared artifact-provenance resolver that accepts a cursor interval (or CT delivery date), resolves the selected daily artifact with the existing nearest-past fallback rules, and identifies the artifact's actual map run and SF window. Use artifact provenance rather than a fresh newest-window lookup.
* Commit 1 — Extend the day-scoped `/map/scorecard` response with `fit_metadata`: `run_id`, `window_start`, `window_end`, `sf_oos_r2`, `coverage`, `sf_stability`, artifact delivery date, and `basis` (`artifact` or `nearest_past`). Do not add a second browser request for this metadata.
* Commit 1 — Keep `/map/summary` bootstrap metadata as an optional latest-map overview only, or remove it from the SidePanel contract; do not reinterpret its latest-window semantics as selected-date metadata.
* Commit 2 — In `MapWorkspace`, derive `fitMeta` from the scorecard response and provide it to `SidePanel` instead of bootstrap `mapMeta`; remove the standalone fit-metadata client and route.
* Commit 2 — Render `SF Window · <date>` above the diagnostics. For a nearest-past fallback, state that the diagnostics belong to the fallback artifact/window; for missing artifacts, show unavailable values rather than the latest fit.
* Commit 3 — Add service and route tests for CT day resolution, selected artifact provenance, nearest-past fallback, missing artifacts, the historical-window guarantee, and the combined scorecard response.
* Do NOT touch: the SF fitting/evaluation algorithms, `sf_window_meta` schema, map-refresh cadence, or how `compute.evaluation.sf --persist-eval` writes diagnostics.

## Acceptance

* [ ] Scrubbing to two delivery days backed by different SF windows returns different window provenance and the corresponding persisted diagnostics.
* [ ] The SidePanel never displays newest-window diagnostics for a historical artifact backed by another window.
* [ ] A nearest-past artifact fallback is visibly labelled with the actual artifact and SF window used.
* [ ] Missing historical artifacts show unavailable SF Window values instead of misleading latest-fit values.
* [ ] The SidePanel obtains scorecard and fit metadata from one `/map/scorecard` request; no standalone fit-metadata route or client call remains.
* [ ] Existing latest-map bootstrap behavior remains available where needed, and focused API/UI tests pass.
