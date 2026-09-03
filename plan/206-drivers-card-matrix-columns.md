# 206 - drivers-card-sortable-columns

Type: refactor
Branch: refactor/206-drivers-card-matrix-columns

## Goal

* Give the node driver lists **sortable** columns so one table replaces the old drivers/exposure toggle.
* Columns for a node: **SF, Side, μ, $/MWh**, plus **binding hours** and a **`*`** where the SF was capped.
* Sorting does the toggle's job: sort by **$/MWh** for the drivers view, by **SF** for structural exposure; the `*` flags rows the fit could not trust.
* Two surfaces get this:
  * **Map node card** (`components/map/DetailCard.tsx`) — the pinned-SP driver list.
  * **Matrix Node Detail frame** (`components/matrix/MatrixReadDetail.tsx`) — the `/matrix` read pane's node table.
* Leave the SF/matrix grid a plain compact matrix — no per-row columns or sort there.
* Constraint reach / constraint detail is unchanged (no sort needed).

## Context

* Both node lists already showed a subset of these fields; the change is to make the columns sortable and to fold the separate "exposure" view (a toggle on the map card, a `<details>` disclosure on the matrix frame) into one sortable table.
* A capped SF (`sf_clipped` / `|SF| >= SF_ABS_CAP`) is the "not structurally sound" signal — the fit pinned the column at its clip, a bound rather than a measurement. Marking it inline lets a reader sort by SF and see which strong exposures are trustworthy.
* The map card's `exposures` response already carries `sf`, `mu`, `contribution`, `binding_hours`, `sf_clipped`. The matrix frame's analysis term did **not** — it needed the two structural fields added.

## Approach

### Map node card — `DetailCard.tsx` (+ `MapWorkspace.tsx`, `useConstraintSelection.ts`)

* One sortable table, columns `Constraint | SF | Side | μ | $/MWh | Bind`, `*` on capped SF. Default keeps the server's contribution (drivers) order.
* Drop the drivers/exposure toggle, the `exposureRank` plumbing, and the "Gross" column; keep the `exposures()` fetch (contribution ranking) and the reach card.

### Matrix Node Detail frame — `MatrixReadDetail.tsx`

* One sortable `DriverTable` over the node's **full nonzero-SF set** (`structural_terms`, the superset that includes the drivers). Default sort `$/MWh` (magnitude) = drivers; sort SF = structural exposure. Replaces the old two-table split (current-hour drivers + `Structural exposure` `<details>`).
* Columns `constraint | SF | side | μ | $/MWh | bind`, `*` on capped SF, footnote when any row is capped.

### Backend — add the two structural fields to the analysis term

* `api/schemas/analysis.py`: `AnalysisContributionTerm` gains `binding_hours: int` and `sf_clipped: bool`.
* `api/services/analysis/panels/catalog.py`: `_terms` / `_structural_terms` populate them (`binding_hours` per constraint; `sf_clipped = |SF| >= SF_ABS_CAP`).
* `api/services/analysis/queries.py`: `node_response` computes delivery-day `binding_hours` and passes it to the builders.
* No new endpoint or DB query; `sf`, `μ`, `$/MWh`, `side` were already derivable.

### Untouched

* The SF/matrix grid (`MatrixGrid.tsx`) — compact matrix, no columns, no sort.
* The constraint reach card / constraint read.

## Acceptance

* [ ] Map node card: one sortable table (SF, Side, μ, $/MWh, binding, `*`), no toggle, no Gross.
* [ ] Matrix Node Detail: one sortable table over the full nonzero-SF set (SF, side, μ, $/MWh, bind, `*`), replacing the structural `<details>`.
* [ ] Clicking a column header sorts; clicking again reverses. Both tables open in the drivers ($/MWh) order.
* [ ] Capped-SF rows show `*`; a footnote explains it.
* [ ] Pinning a constraint still opens the reach card; the SF/matrix grid is unchanged.
* [ ] `web` builds; `api` analysis tests pass.
