# 0100 - map-window-and-prediction-fixes

Type: fix
Branch: fix/0100-map-window-and-prediction-fixes

## Goal

* Make "Load Window" replace the loaded window instead of appending to it: the timeline shows only the submitted range and the cursor lands on that range's start.
* Stop the prediction pane from borrowing realized ERCOT rows when no forecast covers the window — show nothing on the prediction side instead.

## Context

* The three prefetch caches (`ercotCache`, `ercotSppCache`, `forecastCache` in `web/src/api/prefetch.ts`) are module-level `Map`s that accumulate across loads. `getAvailableTimestamps()` returns their union, so each load *adds* frames. A `clearCache()` exists but is never called.
* Because a newly loaded range usually sorts *after* the lingering frames, `setCurrentIndex(0)` lands on an old frame → "nothing happened." Clearing first makes index 0 the new range's start.
* The June-30-on-initial-load observation is stale forecast data (backend serves the promoted run's latest operating day, `MAX(delivery_date)` in `forecast_nodal`), not a frontend bug. The "follow latest prediction" default is intended and stays; the additive cache only made June 30 *linger* after a reload. No landing-behavior change.
* Prediction fallback: `App.tsx` `leftRows = hasForecast ? forecastRows : spRows` makes the dual left pane render realized rows (labeled `PREDICTION · placeholder (= actual)`) when no forecast exists. Basis view already blanks correctly (`basisRows` is `[]` without a forecast) — only the dual left pane needs fixing.

## Approach

### Commit 1 — fix additive window load (Bugs 1-linger, 2)

* Work in: `web/src/api/prefetch.ts`
* Entry point: `prefetchWindow(start?, end?)`
* Call `clearCache()` at the top of `prefetchWindow`, before any fetch, on **both** the explicit-window and default-landing paths, so the caches only ever hold the current window. `clearCache()` already resets `forecastRunId`.
* Verify `handleLoadWindow` in `web/src/App.tsx` needs no change: it already recomputes `timestamps`, window-wide stats, sparkline, and `setCurrentIndex(0)` (or snaps to `cursorTs`) after the prefetch resolves — those now operate on a fresh cache.
* Do NOT change the landing default (still serves the run's latest operating day) and do NOT touch the backend.

### Commit 2 — prediction pane shows nothing without a forecast (Bug 3)

* Work in: `web/src/App.tsx`
* Entry point: the `leftRows` / `leftPane` derivation (~L580-663).
* Change `leftRows` so it is `forecastRows` only (already `[]` when no forecast) — drop the `: spRows` fallback. Let the pane render empty rather than duplicating the actual map.
* Update the prediction pane's labels for the no-forecast case: the `pane-badge` (`predictionLabel`) and the `Legend` `paneLabel` should read as "no forecast this window" rather than `placeholder (= actual)`, so the empty pane is self-explanatory.
* Confirm the left pane's stats fallbacks (`leftMcStats`, `leftLmpStats`) are harmless with empty rows (no lit SPs → nothing to color); simplify only if they read as misleading.
* Do NOT change the basis view (already blank without a forecast) or the actual/right pane.

## Acceptance

* [ ] Loading window A then window B shows only B's frames on the timeline (frame count == B's hours, not A+B), with the cursor at B's first frame.
* [ ] Re-submitting the same range visibly reloads (cursor resets to the start) rather than appearing to do nothing.
* [ ] Initial landing still opens on the latest prediction's operating day (unchanged behavior).
* [ ] In dual view, a window with no forecast renders an empty prediction (left) pane — no ERCOT rows duplicated — with a badge/legend that says there's no forecast for the window.
* [ ] Basis view and the actual (right) pane are unchanged.
