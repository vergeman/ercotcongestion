# 0153 - matrix-detail-market-state-and-labels

Type: feat
Branch: feat/0153-matrix-detail-market-state-and-labels

## Goal

* Label Matrix SF row shadow prices explicitly as Forecast mu and DAM mu.
* Add the selected node's forecast and realized congestion/LMP snapshot to Matrix Detail.
* Explain why Basis is unavailable from Constraints with an accessible hover/focus tooltip.

## Context

* `MatrixGrid` currently abbreviates the two always-visible row prices as `F` and `DAM`, although they are respectively forecast and published DAM mu.
* Matrix Detail already provides the right structural evidence: constraint reach plus daily constraint facts, and a node's complete `-SF * mu` driver column; it does not yet show the current market-value snapshot that `DetailCard` shows on the Map.
* `/forecast_range` and `/ercot_range` can derive the required values but are full-network playback payloads; a selected-node Detail request should return only its own cursor-hour state.
* The disabled Basis button has a native `title`, but disabled controls do not reliably receive hover/focus events; the app has a reusable accessible `Tooltip` trigger for this case.

## Approach

### 1. Make SF grid shadow-price labels unambiguous

* Work in: `web/src/components/matrix/MatrixGrid.tsx` and its Matrix styling/tests.
* Entry point / primary change: `AxisHeaderBody` constraint header.
* Replace `F $…` with `Forecast mu $…` and retain `DAM mu $…`, keeping both values visible and the active source emphasis unchanged.
* Preserve DAM pending/partial formatting, the selected value toggle, existing matrix orientation, and compact responsive wrapping.

### 2. Return one node's cursor-hour market state with its Detail attribution

* Work in: `api/analysis.py`, `api/models.py`, `api/tests/test_analysis.py`, `web/src/api/types.ts`, and `web/src/api/analysisNode.ts`.
* Entry point / primary change: `GET /analysis/node`'s single-hour response.
* Add a nullable `market_state` object to the available node response, with `forecast_congestion`, `forecast_lmp`, `realized_congestion`, and `dam_lmp` (plus the forecast lambda provenance when a persisted lambda is used).
* Resolve the forecast P50 from the same resolved forecast run, delivery date, horizon, settlement point, and requested cursor hour as the node attribution. Resolve forecast LMP as P50 plus the same settled-or-persisted DAM system-lambda convention used by `/forecast_range`; do not invent an LMP when either component is absent.
* Resolve realized DAM LMP from `ercot_dam_spp` at that exact hour and settlement point, and realized congestion as DAM SPP minus the exact-hour system lambda. Preserve `null` for missing/unpublished ERCOT rows rather than returning zero.
* Extract or share the system-lambda fallback logic with `/forecast_range` so Map and Matrix cannot disagree about an unsettled forecast LMP. Keep whole-day `/forecast_range` and `/ercot_range` response shapes unchanged.
* Return the state only for one selected cursor hour. For a multi-hour `/analysis/node` request, leave it absent/null (rather than implying an aggregate is an instant); retain the existing full-column attribution and coverage semantics.
* Add API coverage for settled values, persisted forecast lambda, missing forecast/market components, and exact-hour selection without changing current attribution assertions.

### 3. Present the node snapshot without duplicating Detail evidence

* Work in: `web/src/components/matrix/MatrixReadDetail.tsx` and Matrix Detail styling/tests.
* Entry point / primary change: `NodeRead` facts above the attribution totals.
* Render a compact, clearly labeled current-hour block for Forecast (P50) Congestion, Realized Congestion, Forecast LMP, and DAM LMP; use `$…/MWh` and an em dash for unavailable values.
* Keep the existing Forecast/DAM `-SF * mu` attribution toggle and its DAM-pending guard. The four-value snapshot is informational and remains visible independently of which attribution basis is selected.
* Keep the current constraint Detail facts and node structural evidence (net attribution, SF coverage, ESSP count, and full driver table). Do not re-add removed peak mu/SF stats: daily constraint facts already cover magnitude/frequency, while the node driver's selected-hour table is the more actionable explanation. If a future peak comparison is wanted, scope it as a separate daily time-series/statistics feature rather than mixing it into this cursor-detail pane.

### 4. Make the disabled Basis prerequisite discoverable

* Work in: `web/src/workspaces/MatrixWorkspace.tsx`.
* Entry point / primary change: the disabled Basis lens tab.
* Wrap the disabled button in the shared `Tooltip` trigger when Constraints is active, with copy: `Basis is available only on the Nodes tab because it compares two settlement points.` Ensure the wrapper is reachable by pointer and keyboard without making the disabled action operable.
* Preserve the existing behavior that switching to Constraints exits the Basis lens, the Node-tab enabled state, and the DAM-source availability tooltip.

## Acceptance

* [ ] Every Matrix SF constraint header visibly says `Forecast mu` and `DAM mu`; source emphasis and DAM unavailable states remain correct.
* [ ] Selecting a node in Detail shows forecast P50 congestion/LMP and realized congestion/DAM LMP for the scrubbed hour, with null/missing values rendered as unavailable rather than zero.
* [ ] The node's market snapshot and its full Forecast/DAM driver attribution stay aligned to the selected delivery day, run, horizon, and cursor hour; Map and Matrix use the same forecast-LMP lambda convention.
* [ ] Detail continues to show full structural evidence without reintroducing ambiguous peak statistics.
* [ ] Hovering or focusing disabled Basis from Constraints explains that Nodes is required; Basis remains disabled and enables normally on Nodes.
* [ ] Focused analysis API tests plus the Matrix frontend type/lint checks pass.
