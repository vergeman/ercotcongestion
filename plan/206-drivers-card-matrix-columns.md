# 206 - drivers-card-matrix-columns

Type: refactor
Branch: refactor/206-drivers-card-matrix-columns

## Goal

* Simplify the map node detail card to one list: the constraints that drove this node this hour.
* Remove the "Gross" column and the drivers/exposure toggle from that card.
* Move the structural fields (binding hours, peak |SF|, clip marker) into `/matrix` as visible, sortable columns.
* Keep the matrix default row order exactly as it is today ($/MWh contribution).

## Context

* The node card's "exposure" tab ranks by |SF|, which floats to the top the constraints the fit is least sure of (pinned at ±1) and ones that never bound — it reads as noise.
* The "Gross" column is a magnitude-share number that doesn't add up on screen and misleads more than it helps.
* Nothing is lost: every structural field already exists on the matrix frame (`binding_hours`, `max_abs_sf`, and `sf_abs_cap` for the clip marker), so this is a relocation, not a deletion — and needs no backend change.

## Approach

* Work in: `web/src/components/map/DetailCard.tsx`, `web/src/workspaces/MapWorkspace.tsx`, `web/src/features/*` (the `loadExposures`/`useConstraintSelection` path), `web/src/components/matrix/MatrixGrid.tsx`.
* Map node card (`DetailCard.tsx` -> `ExposuresBody`):
  * Delete the "Gross" column and its `node_gross_total` usage.
  * Delete the drivers/exposure toggle and the |SF|-ranked path; the node list is always "what drove this hour."
  * Remove the now-dead toggle plumbing: `exposureRank` / `onChangeExposureRank` props and the matching state in `MapWorkspace.tsx`.
* Keep, do not delete: the `exposures()` fetch itself — the drivers list still uses it (call it with the contribution ranking only). The constraint->node **reach** card (pinned constraint) is unchanged.
* Matrix (`MatrixGrid.tsx`):
  * Surface as row columns: **binding hours**, **peak |SF|**, and a **`*` clip marker** where `|SF| >= frame.sf_abs_cap` (the check already exists at `MatrixGrid.tsx:75`; the values are already on `MatrixRow`).
  * Add click-to-sort on the constraint rows. Sortable by: **$/MWh contribution (default)**, forecast mu, DAM mu, binding hours, peak |SF|. Re-click reverses direction.
  * Default sort is unchanged — the current `$/MWh` contribution order stays the initial view.
* Do NOT touch: any API service or schema (`api/services/matrix/frame.py`, `api/services/map/detail.py`), and do NOT remove the `exposures()` endpoint.

## Acceptance

* [ ] Map node card shows only the "Drove this hour" list — no Gross column, no drivers/exposure toggle.
* [ ] Pinning a constraint still opens the constraint->node reach card as before.
* [ ] Matrix rows show binding hours, peak |SF|, and a `*` on any row with a clipped cell.
* [ ] Clicking a matrix column header sorts the rows by it; clicking again reverses.
* [ ] Matrix opens in the same $/MWh order it does today.
* [ ] No backend or schema files changed; `web` builds.
