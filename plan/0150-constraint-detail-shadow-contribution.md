# 0150 - constraint-detail-shadow-contribution

Type: feat
Branch: feat/0150-constraint-detail-shadow-contribution

## Goal

* Show the selected constraint's cursor-hour forecast shadow price in its DetailCard.
* Add a `Contrib` column for each constituent settlement point, calculated as `−SF × shadow` in $/MWh.
* Keep the card's constraint reach and cursor-hour values aligned to the same daily artifact.

## Context

* The constraint DetailCard currently receives signed constituent SFs and a day-wide binding-hours count from `/map/reach`, but no cursor-hour μ value.
* `/map/reach` is already requested with the map scrubber timestamp and reads the matching CT-day artifact; its `E_mu` holds the forecast μ vector used by the map's existing `−SF × μ` decomposition.
* The Matrix may separately show realized DAM μ when available; this change is scoped to the constraint card's artifact-backed forecast μ and does not introduce a source toggle.

## Approach

* Work in: `api/models.py`, `api/map.py`, `api/tests/test_map.py`, `web/src/api/types.ts`, and `web/src/components/map/DetailCard.tsx`.
* Entry point / primary change: `ConstraintReach` / `get_map_reach` and `ReachBody`.
* Add a nullable cursor-hour `shadow_price` field to the reach response; when `t` is present and belongs to the artifact, populate it from `artifact.E_mu[constraint]`; retain `null` for no cursor instant or unavailable responses.
* Preserve the existing daily `binding_hours`, SF selection/filtering, fallback provenance, and reach payload behavior; do not query or substitute realized DAM shadow prices.
* In the constraint DetailCard, render a `Shadow Price` row using signed $/MWh formatting, then add a rightmost `Contrib` header and signed `−SF × shadow` value for every displayed constituent node; render an em dash when no cursor-hour shadow is available.
* Expand the shared reach header/row grid so Settlement Point, SF, and Contrib stay aligned in desktop, sticky-scroll, and mobile layouts; add concise tooltip/copy identifying the formula and units.
* Add endpoint coverage for the exact cursor-hour shadow price, including a non-default μ value and absent/unavailable behavior; verify the contribution convention against the existing `node_contributions` sign convention. Run the focused API tests and the DetailCard TypeScript check.
* Do NOT touch: SF fitting, artifact persistence, DAM μ selection, map recoloring, reach thresholds, or node-driver ranking.

## Acceptance

* [x] `/map/reach` returns the selected constraint's artifact `E_mu` value for a valid requested interval and `null` when no interval-specific value is available.
* [x] The constraint DetailCard displays `Shadow Price` in signed $/MWh and keeps `Binding hours`, import, and export counts unchanged.
* [x] Every listed constituent row displays its signed $/MWh contribution as `−SF × shadow`, with aligned `SF` and `Contrib` columns on desktop and mobile.
* [x] Focused `/map/reach` tests and `npx tsc --noEmit -p tsconfig.app.json` in `web/` pass.
