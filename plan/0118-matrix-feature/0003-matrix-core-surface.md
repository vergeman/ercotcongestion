# 0003 - matrix-core-surface

Type: feat
Branch: `feat/0118-matrix-feature/0003-matrix-core-surface`
Source: `plan/0118-matrix-feature/sprint-matrix.md`

## Goal

* Replace the placeholder with a readable, bounded constraint × settlement-point matrix.
* Render Shift Factor and Contribution values from the same returned frame.
* Support Forecast and ERCOT DAM `μ` without changing row/column order.

## Dependency and merge position

* Start after `0001-explorer-shared-shell` and `0002-matrix-frame-api` are merged.
* Use the shared shell timestamp as the only time cursor and consume the frame API contract from 0002.
* Merge when the core matrix, toggles, availability states, and shared scrubber work end to end; selection remains deferred.

## Required context and invariants

* The default rectangle is bounded (30 × 40), so semantic HTML or CSS grid is sufficient; virtualization is not required.
* Dense Matrix frames need a separate bounded cache from `web/src/api/prefetch.ts`.
* Shift Factor is `SF[c, sp]`; Contribution is calculated in the browser as `-sf * selectedRowMu`.
* Forecast and ERCOT DAM use identical implied SF. Only row `μ` changes.
* Missing or unpublished DAM is unavailable, never zero.
* Shadow Price remains row metadata, not a third value mode.
* Row/column ordering is frozen by the API for the loaded delivery day. Playback and toggles must preserve it.
* Clicks must not change the matrix universe; this branch does not add click selection.
* The UI must not imply that recovered implied SF is an official ERCOT shift factor.

## Approach

* Work primarily in:
  * `web/src/pages/MatrixPage.tsx` or `web/src/workspaces/MatrixWorkspace.tsx`;
  * new `web/src/components/matrix/`;
  * `web/src/api/client.ts`;
  * `web/src/api/types.ts`; and
  * matrix color/format helpers with focused tests where supported.
* Add frontend types matching the frame contract exactly.
* Fetch by the shell's selected timestamp; cancel or ignore stale requests during fast scrubbing.
* Cache a bounded number of frames by run/day/timestamp plus row limit, column set, and column limit.
* Render sticky constraint row headers, sticky compact SP headers, scrollable cells, timestamp/provenance label, concise legend, and explicit coverage/unavailable messaging.
* Provide:

  ```text
  Value:    Shift Factor | Contribution
  μ source:                Forecast | ERCOT DAM
  ```

* Hide the `μ source` control in Shift Factor mode.
* Default first entry to Shift Factor, or retain the user's choice for the current session.
* Disable ERCOT DAM when the whole hour is pending. In partial status, mark only unmatched rows/cells unavailable.
* Follow the established sign/color convention: positive SF/export blue, negative SF/import red, near-zero low emphasis.
* Use separate, labeled numeric domains for dimensionless SF and `$/MWh` Contribution.
* Add a footer/summary showing the sum of displayed constraint contributions, labeled **visible-row contribution**. Never call it total nodal congestion unless all modeled constraints are included.
* Make row headers, column headers, and cells keyboard focusable with semantic labels.

## Explicit states

* Initial frame loading.
* Frame replacement during playback without flashing the page.
* Forecast-only future hour.
* ERCOT DAM pending.
* Partial DAM key match.
* Historical day without an artifact.
* Empty bounded result.
* API/network error with retry.
* Safe small-screen presentation even if complete mobile interaction is deferred.

## Out of scope

* Selection/inspector, hover tooltips, search, filters, pins, embedded map, all-data virtualization, or new server-side analytics.

## Acceptance

* [x] The same matrix switches among SF, Forecast Contribution, and ERCOT DAM Contribution.
* [ ] A fixture contribution displays `-SF × μ` at the documented precision.
* [x] Timestamp, value, and source changes do not reorder rows/columns within a delivery day.
* [x] A future hour never displays DAM zeroes.
* [x] Units, sign convention, value source, timestamp, and fit provenance are visible.
* [x] A stale response cannot replace the newest timestamp after rapid scrubbing.
* [ ] The default 30 × 40 surface scrolls smoothly on supported desktop browsers.
* [x] The Matrix has a safe small-screen state.
* [ ] Frontend build and canonical checks pass.

Verification still needed: exercise a fixture contribution and the 30 × 40
surface in a supported browser, then run the frontend checks under the
project's supported Node/toolchain. The local Node 18 environment has an
incomplete dependency installation and cannot run those checks.

## Merge boundary

Merge when the Matrix's core analytical surface is correct and usable end to end, with cells intentionally not yet selectable.
