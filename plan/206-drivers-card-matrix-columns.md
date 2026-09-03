# 206 - drivers-card-sortable-columns

Type: refactor
Branch: refactor/206-drivers-card-matrix-columns

## Goal

* Give the **Matrix Node Detail frame** (`/matrix` read pane) a sortable driver table so one table does the job of the old drivers table plus the separate structural-exposure disclosure.
* Column order for a node: **bind, side (import/export), SF, μ, $/MWh**, with a **`*`** where the SF was capped.
* Sorting replaces the toggle: sort by **$/MWh** for the drivers view, by **SF** for structural exposure; the `*` flags rows the fit could not trust.
* The chosen sort **persists** when you click to another node.
* Simplify the **map node card** to the single "drove this hour" list — no drivers/exposure toggle, no "Gross" column. (No sortable columns are added to the map card.)
* Leave the SF/matrix grid a plain compact matrix — no per-row columns or sort there.
* Constraint reach / constraint detail is unchanged (no sort needed).

## Context

* The Matrix node Detail already showed SF/side/μ/$/MWh as a static "current-hour drivers" table with a separate `Structural exposure` `<details>`. The change makes the columns sortable and folds both into one table.
* A capped SF (`sf_clipped` / `|SF| >= SF_ABS_CAP`) is the "not structurally sound" signal — the fit pinned the column at its clip, a bound rather than a measurement. Marking it inline lets a reader sort by SF and see which strong exposures are trustworthy.
* The analysis term (`AnalysisContributionTerm`) did not carry binding hours or a clip flag, so those two fields were added to the backend; `sf`, `μ`, `$/MWh`, `side` were already derivable.

## Approach

### Matrix Node Detail frame — `MatrixReadDetail.tsx`

* One sortable `DriverTable` over the node's **full nonzero-SF set** (`structural_terms`, the superset that includes the drivers). Default sort `$/MWh` (magnitude) = drivers; sort SF = structural exposure. Replaces the old two-table split.
* Columns `constraint | bind | side | SF | μ | $/MWh`, `*` on capped SF, footnote when any row is capped.
* Sort state is owned by the frame (above `NodeRead`), so it survives switching between nodes.

### Backend — add the two structural fields to the analysis term

* `api/schemas/analysis.py`: `AnalysisContributionTerm` gains `binding_hours: int` and `sf_clipped: bool`.
* `api/services/analysis/panels/catalog.py`: `_terms` / `_structural_terms` populate them (`binding_hours` per constraint; `sf_clipped = |SF| >= SF_ABS_CAP`).
* `api/services/analysis/queries.py`: `node_response` computes delivery-day `binding_hours` and passes it to the builders.
* No new endpoint or DB query.

### Map node card — `DetailCard.tsx` (+ `MapWorkspace.tsx`, `useConstraintSelection.ts`)

* Reduced to the single "drove this hour" contribution list: dropped the drivers/exposure toggle, the `exposureRank` plumbing, and the "Gross" column. Kept the `exposures()` fetch (contribution ranking) and the reach card. No sortable columns here.

### Untouched

* The SF/matrix grid (`MatrixGrid.tsx`) — compact matrix, no columns, no sort.
* The constraint reach card / constraint read.

## Acceptance

* [x] Matrix Node Detail: one sortable table over the full nonzero-SF set, columns `bind, side, SF, μ, $/MWh`, replacing the structural `<details>`.
* [x] Clicking a column header sorts; clicking again reverses. The table opens in the drivers ($/MWh) order.
* [x] The selected sort persists when switching to another node.
* [x] Capped-SF rows show `*`; a footnote explains it.
* [x] Map node card shows only the "drove this hour" list — no drivers/exposure toggle, no Gross column, no sortable columns.
* [x] Pinning a constraint still opens the reach card; the SF/matrix grid is unchanged.
* [x] `web` builds; `api` analysis tests pass (70 passed).
