# 0004 - matrix-selection-inspector

Type: feat
Branch: `feat/0118-matrix-feature/0004-matrix-selection-inspector`
Source: `plan/0118-matrix-feature/sprint-matrix.md`

## Goal

* Add explicit row, column, and cell selection.
* Render one persistent, collapsible inspector below the matrix.
* Link selected objects to the existing map without embedding a duplicate map.

## Dependency and merge position

* Start after `0003-matrix-core-surface` is merged.
* Reuse only the loaded frame and its metadata for inspector calculations.
* Merge when selection answers “what exactly am I looking at?” and existing map geography is reachable; historical charts/dossiers remain deferred.

## Required interaction contract

* Clicking a row header selects one constraint.
* Clicking a column header selects one settlement point.
* Clicking a cell selects the exact constraint/SP pair.
* Clicking never reorders, filters, expands, or otherwise changes the matrix universe.
* Selection persists across hour and value-mode changes while its stable row/column identifiers remain in the frame.
* Collapsing the inspector requires an explicit user action and does not clear selection.
* The shared timestamp remains unchanged during Matrix → Map navigation.
* A selection is addressable in the URL and restores into the appropriate workspace on load, Back/Forward, or return navigation.
* The selected Matrix row, column, or cell is scrolled into the Matrix viewport when restored from a URL.

## Selection model

```ts
type MatrixSelection =
  | { kind: "constraint"; constraintKey: string }
  | { kind: "settlementPoint"; settlementPoint: string }
  | { kind: "cell"; constraintKey: string; settlementPoint: string }
  | null;
```

Store stable identifiers, never row/column indices.

## Inspector content

### Selected cell

* Constraint/contingency key and settlement-point name.
* Implied SF.
* Exact-hour Forecast `μ` and `-SF × forecast μ`.
* Exact-hour ERCOT DAM `μ` and `-SF × DAM μ`, or a precise unavailable label.
* “View constraint on map” and “View settlement point on map” actions.

### Selected constraint

* Name, contingency/type, daily rank, binding/active hours, and maximum `|SF|`.
* Forecast and DAM `μ` at the selected hour.
* Strongest visible positive and negative SP exposures.

### Selected settlement point

* Name, type, and load zone.
* Visible-row forecast and DAM contribution sums.
* Strongest visible constraint drivers.
* A warning that visible-row sums are not total congestion when the response is truncated.

## Approach

* Compute all inspector details from the loaded frame; clicking must issue no metadata request.
* Reuse the matrix's shared arithmetic and formatting helpers so cells and inspector cannot disagree.
* Add persistent selected styles, keyboard operation, focus behavior, and `aria-selected`.
* Add deep links:
  * `/matrix?constraint=<encoded key>`
  * `/matrix?sp=<encoded point>`
  * `/matrix?constraint=<encoded key>&sp=<encoded point>` for an exact cell
  * `/map?constraint=<encoded key>`
  * `/map?sp=<encoded point>`
* Update the Matrix URL when a row, column, or cell is selected; teach `MatrixWorkspace` to consume those parameters and restore the inspector selection when available.
* Update the Map URL when a constraint or settlement point is selected; teach `MapWorkspace` to consume those parameters and select the corresponding object when available.
* Keep the Explorer session mounted across route changes so Matrix → Map → Matrix retains the loaded frame, selection, inspector state, and timestamp.
* If the current map artifact cannot represent the target, retain the requested selection and show a graceful “not present in this fit/window” state.
* Keep the inspector below the matrix and make collapse/expand layout stable.

## Out of scope

* New historical queries, charts, dossiers, embedded map, hover metadata, discovery controls, or changes to the matrix universe.

## Acceptance

* [ ] Row, column, and cell selections are visually distinct and keyboard operable.
* [ ] Inspector arithmetic matches the selected cell for both available `μ` sources.
* [ ] Inspector content updates during playback while selection remains stable.
* [ ] Collapse/expand neither clears selection nor unpredictably resizes the page.
* [ ] Matrix selection updates `/matrix` with the constraint, settlement point, or exact cell identifiers and restores the inspector selection from that URL.
* [ ] Map and Matrix selections update their respective URLs, and browser Back/Forward restores the selected object without changing the shared timestamp.
* [ ] Deep links open the existing map with the selected constraint or SP when present.
* [ ] Unavailable map targets receive a graceful, explicit state.
* [ ] A URL-restored Matrix selection is scrolled into view within the Matrix grid.
* [ ] No click triggers an N+1 metadata request.
* [ ] Truncated sums are never labeled total nodal congestion.

## Merge boundary

Merge when stable selection and exact arithmetic are clear in the inspector and both object types can be handed off to the existing map.
