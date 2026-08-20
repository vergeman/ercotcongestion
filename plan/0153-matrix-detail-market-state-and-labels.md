# 0153 - matrix-detail-market-state-and-labels

Type: feat
Branch: feat/0153-matrix-detail-market-state-and-labels

## Goal

* Keep the SF grid focused on shift factors while retaining unambiguous Forecast μ and DAM μ evidence on hover and in Detail.
* Make Matrix Detail the complete deep view for a selected node or constraint, including the information presently available in the Map DetailCard.
* Explain why Basis is unavailable from Constraints with an accessible hover/focus tooltip.

## Context

* Constraint-row price/rank metadata made the SF grid crowded; the chosen presentation is constraint name plus muted contingency, with price evidence on hover and in Detail.
* Matrix Detail already provides a constraint's full reach and a node's complete current-hour `-SF * mu` driver column, but its summary does not yet contain all Map DetailCard facts or distinguish current-hour values from daily/structural evidence.
* `/forecast_range` and `/ercot_range` can derive the required values but are full-network playback payloads; a selected-node Detail request should return only its own cursor-hour state.
* The disabled Basis button has a native `title`, but disabled controls do not reliably receive hover/focus events; the app has a reusable accessible `Tooltip` trigger for this case.

## Approach

### 1. Keep SF grid headers legible

* Work in: `web/src/components/matrix/MatrixGrid.tsx` and its Matrix styling/tests.
* Entry point / primary change: `AxisHeaderBody` constraint header.
* When constraints are rows, show only the constraint name and muted contingency; do not fit rank, Forecast μ, or DAM μ into the grid header.
* Retain Forecast μ, DAM μ, and rank in the cell hover evidence. Preserve DAM pending/partial formatting and the selected value toggle.

### 2. Return one node's cursor-hour market state with its Detail attribution

* Work in: `api/analysis.py`, `api/models.py`, `api/tests/test_analysis.py`, `web/src/api/types.ts`, and `web/src/api/analysisNode.ts`.
* Entry point / primary change: `GET /analysis/node`'s single-hour response.
* Add a nullable `market_state` object to the available node response, with `forecast_congestion`, `forecast_lmp`, `realized_congestion`, `forecast_error`, and `dam_lmp` (plus the forecast lambda provenance when a persisted lambda is used).
* Resolve the forecast P50 from the same resolved forecast run, delivery date, horizon, settlement point, and requested cursor hour as the node attribution. Resolve forecast LMP as P50 plus the same settled-or-persisted DAM system-lambda convention used by `/forecast_range`; do not invent an LMP when either component is absent.
* Resolve realized DAM LMP from `ercot_dam_spp` at that exact hour and settlement point, and realized congestion as DAM SPP minus the exact-hour system lambda. Preserve `null` for missing/unpublished ERCOT rows rather than returning zero.
* Extract or share the system-lambda fallback logic with `/forecast_range` so Map and Matrix cannot disagree about an unsettled forecast LMP. Keep whole-day `/forecast_range` and `/ercot_range` response shapes unchanged.
* Return the state only for one selected cursor hour. For a multi-hour `/analysis/node` request, leave it absent/null (rather than implying an aggregate is an instant); retain the existing full-column attribution and coverage semantics.
* Add API coverage for settled values, persisted forecast lambda, missing forecast/market components, and exact-hour selection without changing current attribution assertions.

### 3. Present the node snapshot without duplicating Detail evidence

* Work in: `web/src/components/matrix/MatrixReadDetail.tsx` and Matrix Detail styling/tests.
* Entry point / primary change: `NodeRead` facts above the attribution totals.
* Render a compact, clearly labeled current-hour block for Forecast (P50) Congestion, Realized Congestion, Forecast Error, Forecast LMP, and DAM LMP; use `$…/MWh` and an em dash for unavailable values.
* Keep the existing Forecast/DAM `-SF * mu` attribution toggle and its DAM-pending guard. The hourly snapshot is informational and remains visible independently of which attribution basis is selected.
* Keep the existing full driver table and current-basis attribution guard; the market snapshot is informational and remains visible independently of which attribution basis is selected.

### 4. Make Detail summaries a paired hourly and daily/structural view

* Work in: `api/analysis.py`, `api/models.py`, `api/tests/test_analysis.py`, `web/src/api/types.ts`, and `web/src/components/matrix/MatrixReadDetail.tsx`.
* Entry point / primary change: a single-constraint analysis response and the summary facts above each Detail evidence list.
* Use one shared two-column summary layout: a **Selected hour** column for cursor-specific market values and a **Daily / structural** column for the selected delivery-day facts. Keep identical label/value tracks in both columns so values scan vertically.
* For a node, show the Map DetailCard-equivalent Forecast congestion, Realized congestion, Forecast Error, Forecast LMP, and DAM LMP in Selected hour. Put zone, settlement-point type, ESSP membership, SF coverage, and driver count in Daily / structural. Keep the full current-hour drivers below; add a separate full structural-exposure view for nonzero SF relationships, including quiet constraints, rather than substituting the Map card's capped list.
* Extend the existing full `/map/reach` payload used by Matrix Constraint Detail with published DAM μ, Forecast Error, daily Forecast μ rank/sum, and full import/export counts. Preserve null for absent/unpublished DAM data; do not add a second constraint-detail endpoint.
* For a constraint, retain the full reach/member evidence and footprint map below the summary. Do not duplicate the Map DetailCard's truncated member list: Matrix Detail must remain the unbounded evidence surface.
* Clearly label Forecast mu versus DAM mu and Forecast Error; do not show a daily aggregate as though it were a cursor-hour value.

### 5. Make the disabled Basis prerequisite discoverable

* Work in: `web/src/workspaces/MatrixWorkspace.tsx`.
* Entry point / primary change: the disabled Basis lens tab.
* Wrap the disabled button in the shared `Tooltip` trigger when Constraints is active, with copy: `Basis is available only on the Nodes tab because it compares two settlement points.` Ensure the wrapper is reachable by pointer and keyboard without making the disabled action operable.
* Preserve the existing behavior that switching to Constraints exits the Basis lens, the Node-tab enabled state, and the DAM-source availability tooltip.

### 6. Redesign the Matrix mobile entity picker

* Work in: `web/src/components/matrix/MatrixSidebar.tsx` and `web/src/workspaces/MatrixWorkspace.tsx`.
* The current collapsed mobile index/search tray is functional but not accepted as the final interaction. Treat search/entity selection as the primary mobile action, not a hidden side panel.
* Research and implement a compact picker that keeps Constraint/Node switching and search immediately discoverable, presents filtered results without making the Detail/SF stage feel displaced, and returns cleanly to the selected entity after a choice.
* Keep horizontal SF-grid inspection, Detail's single-column layout, and keyboard/accessibility semantics intact. Do not change Matrix data contracts as part of this mobile interaction refinement.

## Acceptance

* [x] SF constraint rows show only the constraint name and muted contingency; hover retains Forecast μ, DAM μ, and rank without crowding the matrix.
* [x] Node Detail contains paired Selected hour and Daily / structural summaries, including Forecast P50 congestion, Realized congestion, Forecast Error, Forecast LMP, and DAM LMP; missing values render as unavailable rather than zero.
* [x] Node current-hour market state and full Forecast/DAM driver attribution use the selected delivery day, run, horizon, and cursor hour; Matrix shares the forecast-LMP lambda convention with Map.
* [x] Node Detail offers separate full current-hour drivers and full structural exposure; quiet constraints are not presented as current-hour drivers.
* [x] Constraint Detail contains paired summaries. Its hourly side shows Forecast μ, DAM μ when published, and Forecast Error; its daily/structural side shows daily Forecast rank/sum, binding hours, peak |SF|, and import/export counts.
* [x] Constraint Detail extends the existing full reach response and keeps absent/unpublished DAM μ unavailable rather than zero.
* [x] Matrix Detail exposes Map DetailCard facts while retaining uncapped driver and reach evidence.
* [x] Hovering or focusing disabled Basis from Constraints explains that Nodes is required; Basis remains disabled and enables normally on Nodes.
* [x] Focused analysis/map tests, TypeScript checks, and whitespace checks pass for the implemented groups.
* [ ] Mobile Matrix has an accepted entity-picker interaction: search and Node/Constraint switching remain immediately visible, filtered results are pleasant to use alongside the active stage, and selecting a result returns cleanly to that entity.
