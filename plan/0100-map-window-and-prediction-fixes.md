# 0100 - map-window-and-prediction-fixes

Type: fix
Branch: fix/0100-map-window-and-prediction-fixes

## Goal

* Make "Load Window" replace the loaded window instead of appending to it: the timeline shows only the submitted range and the cursor lands on that range's start.
* Stop the prediction pane from borrowing realized ERCOT rows when no forecast covers the window — show nothing on the prediction side instead.
* Rename the misleading "Basis" quantity (it collides with the power-trading term) to "Forecast Error" throughout — UI copy and internal identifiers.

## Context

* The three prefetch caches (`ercotCache`, `ercotSppCache`, `forecastCache` in `web/src/api/prefetch.ts`) are module-level `Map`s that accumulate across loads. `getAvailableTimestamps()` returns their union, so each load *adds* frames. A `clearCache()` exists but is never called.
* Because a newly loaded range usually sorts *after* the lingering frames, `setCurrentIndex(0)` lands on an old frame → "nothing happened." Clearing first makes index 0 the new range's start.
* The June-30-on-initial-load observation is stale forecast data (backend serves the promoted run's latest operating day, `MAX(delivery_date)` in `forecast_nodal`), not a frontend bug. The "follow latest prediction" default is intended and stays; the additive cache only made June 30 *linger* after a reload. No landing-behavior change.
* Prediction fallback: `App.tsx` `leftRows = hasForecast ? forecastRows : spRows` makes the dual left pane render realized rows (labeled `PREDICTION · placeholder (= actual)`) when no forecast exists. The forecast-error view already blanks correctly (`errorRows` is `[]` without a forecast) — only the dual left pane needs fixing.

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
* Do NOT change the forecast-error view (already blank without a forecast) or the actual/right pane.

### Commit 3 — rename "Basis" → "Forecast Error"

* Work in: `web/src/App.tsx`, `web/src/api/types.ts`, `web/src/lib/colors.ts`, `web/src/components/{layout/Header,map/Legend,map/DetailCard}.tsx`.
* `ViewMode` value `basis` → `forecastError`; `basisColor`/`BASIS_GRADIENT_CSS` → `forecastErrorColor`/`FORECAST_ERROR_GRADIENT_CSS`; the SP decomposition field `basis` → `error`.
* User-facing copy: view tab "Basis" → "Forecast Error"; map/legend label → "Congestion Forecast Error · P50 forecast − realized"; sign labels "pred < / > market" → "under-/over-forecast"; card rows → "Forecast (P50) / Realized / Forecast error".
* Emerald↔magenta ramp unchanged; only the naming and quantity framing (P50 forecast − realized) move.

## Acceptance

Commit 1 — additive window load:

* [x] Loading window A then window B shows only B's frames on the timeline (frame count == B's hours, not A+B), with the cursor at B's first frame.
* [x] Initial landing still opens on the latest prediction's operating day (unchanged behavior).
* [x] `clearCache()` runs at the top of `prefetchWindow` on both the explicit-window and default-landing paths.

Commit 2 — empty prediction pane without a forecast:

* [x] In dual view, a window with no forecast renders an empty prediction (left) pane — no ERCOT rows duplicated — with a badge/legend that says there's no forecast for the window.
* [x] `leftRows` is `forecastRows` only (no `spRows` fallback); the pane badge and Legend `paneLabel` read "no forecast this window".
* [x] The forecast-error view and the actual (right) pane are unchanged in behavior.

Commit 3 — "Basis" → "Forecast Error" rename:

* [x] The view tab reads "Forecast Error"; its map/legend, sign labels, and card rows use the forecast/realized/error wording — no "Basis" strings remain in the UI.
* [x] No `basis` identifiers remain in `types.ts`/`colors.ts`/`App.tsx` (grep clean, except the genuine market-basis mention in `events.ts`); the map colors identically to before.
* [x] App source typechecks clean (`tsc --noEmit -p tsconfig.app.json`, exit 0).
