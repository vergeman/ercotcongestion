# 0222 — Matrix display and loading

Type: fix
Branch: `fix/matrix-display-and-load`

## Goal

* Clarify hourly node metrics and reduce delays when stepping through hours.

## Context

* SF coverage and current drivers were shown under daily/structural stats.
* Clearing detail content, duplicate requests, and rendering full lists caused flashes and delays.

## Approach

### Commit 1 — Clarify hourly node metrics

* Work in: `NodeRead.tsx`, `Fact.tsx`.
* Move SF coverage and driver count into Selected hour; rename the count to “No. Current Drivers”.
* Add brief tooltips: `Σ(−model SF × realized DAM μ) / realized congestion` and `constraint counts where |−SF × μ| > 0`.

### Commit 2 — Preserve detail while fetching

* Work in: `api/analysisNode.ts`, `api/map.ts`, `constraintReachData.ts`, `NodeRead.tsx`, `ConstraintRead.tsx`.
* Reuse cached node results and retain matching detail during hourly refreshes; indicate pending values.
* Deduplicate reach requests by full query; keep shared node requests alive when one caller cancels.

### Commit 3 — Reduce rendering work

* Work in: `MatrixStage.tsx`, `MatrixSidebar.tsx`, `MatrixReadDetail.tsx`, `DriverTable.tsx`, `NodeRead.tsx`, `lib/format.ts`.
* Remove the artificial 220 ms loading overlay.
* Render visible sidebar rows with overscan, preserving selection scrolling and total counts.
* Memoize driver tables/unchanged rows, stabilize sort callbacks and map coordinates, and reuse currency formatters.

## Acceptance

* [x] Hourly metrics have the requested placement, labels, and tooltips.
* [x] Cache/cancellation checks preserve distinct hourly values and share duplicate requests.
* [x] Browser checks confirm hourly coverage updates and scrolling reaches the final sidebar entry.
* [x] TypeScript, focused lint, and currency-format equivalence checks pass.
* [ ] Verify search, pinning, keyboard navigation, and mobile sidebar behavior before merging.
