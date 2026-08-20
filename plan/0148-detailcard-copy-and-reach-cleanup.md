# 0148 - detailcard-copy-and-reach-cleanup

Type: fix
Branch: fix/0148-detailcard-copy-and-reach-cleanup

## Goal

* Make DetailCard congestion and LMP labels unambiguous and consistently capitalized.
* Give driver and constraint-reach lists clearer separation and column labels.
* Remove unsupported confidence caveats from the constraint-reach card.

## Context

* `SpBody` currently says `Forecast (P50)`, `Realized`, `Forecast error`, and `DAM SPP`, though its values are congestion except for the final LMP rows.
* The predicted-LMP `(indicative)` suffix is passed into the node DetailCard when horizon-2 uses persisted lambda.
* `ReachBody` derives ridge-clamp/thin-support warnings from display-only rail thresholds and has no header over its existing SF value column.

## Approach

* Work in: `web/src/components/map/DetailCard.tsx`.
* Entry point / primary change: `SpBody` and `ReachBody`.
* Rename node rows to `Forecast (P50) Congestion`, `Realized Congestion`, `Forecast Error`, and `DAM LMP`; retain the existing values and formatting.
* Remove `lambdaIndicative` from DetailCard/SpBody and stop appending `(indicative)` to `Predicted LMP`; leave the map legend’s persisted-lambda provenance intact.
* Add bottom spacing below `.dc-driver--head`’s border before the first driver value, without changing sticky-header alignment.
* Remove `RAIL_MULTI`, `BODY_FLOOR`, `THIN_HOURS`, `railArtifact`, and the low-confidence/thin-support annotation from the constraint-reach view; keep its factual `Binding hours`, import, and export rows.
* Add a reach-list header aligned to its three-column grid, labeling the settlement-point column and its existing `SF` value column like the node driver list.
* Do NOT touch: reach API payloads/threshold filtering, SF values, forecast persistence behavior, or Legend’s indicative note.

## Acceptance

* [x] A node DetailCard reads `Forecast (P50) Congestion`, `Realized Congestion`, `Forecast Error`, and `DAM LMP`; numbers and units are unchanged.
* [x] Horizon-2 node DetailCards show `Predicted LMP` with no `(indicative)` suffix; the LMP legend still identifies persisted lambda as indicative.
* [x] Driver-list headers have matching 6px gaps from text to border and border to first row, without column drift.
* [x] Constraint-reach cards render no `thin support`, ridge-clamp/low-confidence label, or rail-threshold qualification.
* [x] Constraint-reach rows have aligned settlement-point and `SF` headers, and retain their existing signed SF values and interactions.
* [x] DetailCard ESLint and `npx tsc --noEmit -p tsconfig.app.json` pass in `web/`; full-project lint remains blocked by existing MapWorkspace hook-rule errors and the local ESLint/Node formatter mismatch.
