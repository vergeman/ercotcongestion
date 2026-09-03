# 206 - drivers-card-sortable-columns

Type: refactor
Branch: refactor/206-drivers-card-matrix-columns

## Goal

* Replace the map node card's drivers/exposure toggle with one **sortable** table.
* For a node, the driver rows carry columns: **SF, Side, μ, $/MWh**, plus **binding hours** and a **`*`** where the SF was capped.
* Sorting lets one table do the job of the old toggle: sort by **$/MWh** for the drivers view, by **SF** for structural exposure — and the `*` flags rows the fit could not trust.
* Leave the SF/matrix frame a compact matrix — no per-row columns or sort there.
* Constraint reach card is unchanged (no sort needed).

## Context

* The old card had a drivers/exposure toggle that re-asked the server for a different ranking. One sortable table over the contribution response replaces it: the columns are already on `SpExposure` (`sf`, `sf_clipped`, `mu`, `contribution`, `binding_hours`), so no refetch and no backend change.
* The "Gross" column was a magnitude-share number that didn't add up on screen — dropped.
* A capped SF (`sf_clipped`) is the "not structurally sound" signal: the fit pinned the column at its ±1 clip, a bound rather than a measurement. Marking it inline lets a reader sort by SF and immediately see which of the strong exposures are trustworthy.

## Approach

* Work in: `web/src/components/map/DetailCard.tsx`, `web/src/workspaces/MapWorkspace.tsx`, `web/src/features/map/useConstraintSelection.ts`.
* Node card (`DetailCard.tsx` -> `ExposuresBody`):
  * One table, columns: `Constraint | SF | Side | μ | $/MWh | Bind`. `Side` = import (SF<0) / export (SF>0), per docs/SF.md. `*` on the SF cell when `sf_clipped`.
  * Click a column header to sort; re-click reverses. Default (no click) keeps the server's contribution order — the drivers ranking — so the card opens as the drivers list.
  * Drop the drivers/exposure toggle, the `exposureRank`/`onChangeExposureRank` plumbing, and the "Gross" column + `node_gross_total` usage.
  * Keep the `exposures()` fetch (called with the contribution ranking only) and the constraint->node reach card.
* `MapWorkspace.tsx` / `useConstraintSelection.ts`: remove the `exposureRank` state and handler; `loadExposures` always requests `contribution`.
* Do NOT touch: any API service or schema (`api/services/map/detail.py`), and do NOT remove the `exposures()` endpoint.
* Matrix (`MatrixGrid.tsx`): unchanged — a compact matrix, no structural columns, no sort.

## Decision / follow-up

* The table is the hour's **drivers** (binding constraints): the contribution response drops constraints that did not bind, and `μ`/`$/MWh` are only defined for that hour. That is enough to replicate the old drivers view and flag unsound (capped) rows.
* Extending the table to **quiet, non-binding** constraints (the old "exposure" set) would need the `exposures` service to fill `mu`/`contribution` under `rank=sf` — a backend change, left as a follow-up.

## Acceptance

* [ ] Node card shows one sortable table: SF, Side, μ, $/MWh, binding hours, with `*` on capped-SF rows — no drivers/exposure toggle, no Gross column.
* [ ] Clicking a column header sorts the rows by it; clicking again reverses.
* [ ] The card opens in the drivers ($/MWh contribution) order it does today.
* [ ] Pinning a constraint still opens the constraint->node reach card as before.
* [ ] The SF/matrix frame is a plain compact matrix, unchanged.
* [ ] No backend or schema files changed; `web` builds.
