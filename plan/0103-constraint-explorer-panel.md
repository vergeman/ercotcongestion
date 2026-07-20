# 0103 - constraint-explorer-panel

Type: feat
Branch: feat/0103-constraint-explorer-panel

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Serve a per-day ranked list of constraints ("most congested today") with each constraint's source/sink lobe pair, defaulting to predicted congestion contribution.
* Render a browsable `Constraints` side-panel tab: ranked top-K rows, each drillable into full membership, with hover synced to the map overlay.
* Provide the accessible table/list fallback for the de-piled overview (the overlap-proof way to reach any constraint).

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* Realizes the deferred `plan/pending-constraint-side-panel.md` ("browsable side panel — all members, source/sink lobe pairs, synced hover, a11y fallback"); ranking is list-shaped, which the map cannot do (overlay centroids pile up — the overlap problem that doc names).
* This is the mechanism companion to 0098's basis map — ranking by *predicted* congestion answers "which constraints drive the disagreement on screen." Depends on 0096 (forecast) + the SF+μ artifact + 0098 (basis/overlay); fast-follow to 0098.
* A distinct panel from 0099 (metrics/scorecard) — same side-panel region, different question. Host both as tabs: `[Stats]` (0099) + `[Constraints]` (this); do not merge their content.
* Ranking/reach primitives partly exist: `api/map.py` `/map/reach` (top-k nodes a constraint drives) and `/map/exposures` (top-k constraints driving a node); App already glows the pinned node's drivers.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `api/map.py` (+ schema in `api/models.py`), `web/src/api/client.ts` + `web/src/api/types.ts` (the api layer split, not the stale `web/src/api.ts`), `web/src/components/panels/` (the existing `SidePanel` region + new `ConstraintPanel`), `web/src/components/map/OverviewOverlay.tsx` (hover sync).
* Entry point / primary change: new `GET /map/constraints/ranked?day&basis=predicted|realized&run_id&k&min_frac` → `{run_id, delivery_date, basis, k, n_ranked, constraints[]}` where each row is `{constraint_id, rank, congestion_contribution, mu_mass, reach, n_members, ctype, core_lat, core_lon, source_lobe, sink_lobe}`, ordered by contribution. `source_lobe`/`sink_lobe` are `{lat, lon, peak_sf, n_nodes}` dipole ends. Default `predicted` (the day's fitted `E_mu` from `forecast_sf_artifact`); `realized` swaps the μ series for that day's published DAM shadow prices (`ercot_dam_shadow_prices`, joined on the same `constraint_name|contingency_name` key), keeping the SF structure fixed.
* Ranking metric: `congestion_contribution = mu_mass · reach` — the day-total of the `−E_mu·SF` nodal decomposition (`mu_mass = Σ_ts |μ[ts,c]|`, `reach = Σ_sp |SF[c,sp]|`). Both are surfaced on the row so the score is legible, not black-box. The forecast run is resolved from `forecast_current[ercot]` (this feature's own pointer, not the SF-map `map_run_id`); `ctype`/`core_*` are best-effort-joined from the SF-map's `constraint_geo` so a panel row and its overlay mark share a key.
* Reuse `/map/reach` for a row's node drill-in; do not duplicate that ranking — this endpoint aggregates to the per-day constraint level.
* Panel: ranked top-K rows, each showing its source/sink lobe pair; expand a row to full membership; hovering a row highlights that constraint on the map overlay and vice versa (synced hover).
* Structure the panel as a real list/table so it doubles as the a11y fallback for the de-piled overview.
* Tab it alongside the 0099 `Stats` panel in one side-panel region; a `predicted | realized` toggle sits on the panel.
* Load the `dataviz` skill before any lobe/meter visuals.
* Do NOT: re-rank inside the client (server owns the order); do NOT build a second side-panel region; do NOT block on 0100/0101.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `GET /map/constraints/ranked` returns per-constraint rows ordered by congestion contribution for the given day, with source/sink lobes and member count.
* [ ] Default ranking is predicted contribution; the `realized` toggle reorders to that day's actual congestion.
* [ ] The `Constraints` tab lists the ranked top-K; expanding a row shows full membership; a row drills to its nodes via `/map/reach`.
* [ ] Hovering a row highlights the constraint on the map overlay and hovering the overlay highlights the row (synced both ways).
* [ ] The panel is a keyboard-navigable list/table serving as the a11y fallback for the overview.
* [ ] The panel shares one side-panel region with the 0099 `Stats` tab — no second panel region.
