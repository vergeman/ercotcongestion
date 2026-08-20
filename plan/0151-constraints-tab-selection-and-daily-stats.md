# 0151 - constraints-tab-selection-and-daily-stats

Type: feat
Branch: feat/0151-constraints-tab-selection-and-daily-stats

## Goal

* Make a Constraints-tab row select and open the same locked constraint DetailCard as a map constraint click.
* Move the tab’s existing member-list drill-in to a dedicated expanding chevron.
* Make the tab a daily comparison surface by showing its rank-explaining μ and SF statistics.

## Context

* `ConstraintPanel` row click currently locks map focus and expands `Membership`, while a map/card constraint selection fetches `/map/reach` and opens `DetailCard`’s constraint view.
* Some ranked constraints cannot be reliably selected from a visible map mark, so the tab must be an equivalent selection entry point.
* Ranked responses already include day-level `mu_mass` and `reach` but do not expose their binding-hour count, peak μ, or peak |SF|; `DetailCard` now owns cursor-hour μ and per-member `−SF × μ` detail.

## Approach

* Work in: `web/src/workspaces/MapWorkspace.tsx`, `web/src/components/panels/SidePanel.tsx`, `web/src/components/panels/ConstraintPanel.tsx`, `api/map.py`, `api/models.py`, `api/tests/test_map.py`, and `web/src/api/types.ts`.
* Entry point / primary change: `ConstraintPanel` row actions and `GET /map/constraints/ranked`.
* Pass the existing composite constraint-selection handler to `SidePanel`/`ConstraintPanel`, so clicking a row writes the constraint route, locks map isolation, fetches the cursor-day reach, and opens the constraint DetailCard—the same behavior as a driver-row click.
* Split row controls into a primary selection button and an adjacent labeled chevron button. The chevron alone toggles the existing `Membership` child list; preserve keyboard focus, `aria-expanded`, row hover isolation, and constituent-node hover rings.
* Keep member rows out of the default tab scan. Update caption/tooltips to say click selects and the chevron previews members, avoiding duplicate “click to expand” language.
* Extend each ranked row with basis-aligned daily `binding_hours` and `peak_shadow_price`, calculated from forecast `E_mu` for predicted mode and from the same bounded DAM aggregation used for realized mode. Also return `max_abs_sf` from the artifact row.
* Render a compact daily-stat line beneath each ranked row: μ mass, peak shadow price, binding hours, SF reach, and peak |SF|. Keep the contribution bar, node count, and dipole as the comparison headline; do not render constituent SFs or cursor-hour values here.
* Add API tests for predicted and realized daily summary fields, including a basis change that alters μ-derived fields while SF summaries remain fixed. Add focused component/TypeScript coverage for row selection versus disclosure semantics.
* Do NOT touch: SF fitting, rank ordering/formula, reach thresholds, DetailCard constituent calculations, map-overlay rendering, or the predicted/realized toggle behavior.

## Acceptance

* [x] Clicking any Constraints-tab row opens and locks its constraint DetailCard even when it has no practical map mark.
* [x] The disclosure chevron, not primary row selection, solely expands/collapses the existing member list and remains keyboard accessible.
* [x] The tab displays daily μ mass and SF reach in aligned columns with labels/tooltips; μ mass follows the active basis and SF reach does not. Peak and binding statistics are intentionally not displayed.
* [x] Existing ranked ordering, hover synchronization, node-member interactions, and DetailCard behavior remain intact.
* [x] Focused map API tests and frontend TypeScript checks pass.
