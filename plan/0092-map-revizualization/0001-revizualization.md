# 0001 - revizualization

Type: feat
Branch: feat/0092-0001-revizualization

## Goal

* Replace the single `|SF|`-weighted centroid per constraint with SF-field primitives: a signed **dipole** (positive-lobe → negative-lobe axis) and the per-node SF field, both derived from `implied_shift_factors`.
* Render a selected constraint as a **diverging choropleth** over settlement points (+/− SF); render GTC/corridor constraints as the **SF=0 isoline** ("cut").
* Render the overview as oriented dipole segments colored by binding severity, replacing the overlapping centroid bubbles; keep the click-to-related-nodes behavior.

## Context

* `constraint_geo` collapses each constraint's signed SF field to one `|SF|`-weighted centroid; its own `spread_km` comment admits "a bimodal constraint's centroid can land between its two lobes" — the purple-pile failure mode.
* The full per-node SF field is already persisted in `implied_shift_factors` (constraint × settlement_point × sf); this is a serve/geo + web change, **no new modeling**.
* A constraint is an oriented spatial separation (dipole), not a point; interfaces/GTCs are the most bimodal and pile up hardest.
* Same SF-map pipeline as `0092-sf-incremental-append.md`; sequence the schema/geo work with it.

## Approach

* Work in: prototype scratch first; then `compute/sf/geo_persist.py` (+ `compute/mu/geo.py` derivation), `db/migrations/` (constraint_geo poles), `api/` `/map/*`, the web map component.
* Entry point / primary change: SF-field → dipole/field derivation replacing the centroid collapse.
* **Spike first:** prototype field vs dipole vs isoline against real `implied_shift_factors` (incl. a bimodal GTC) and pick the primitives before writing render code.
* Geo: emit two poles (+/− `|SF|`-weighted centroids) + dipole strength + `max_abs_sf`; expose a downsampled field or top-K nodes per constraint for the choropleth.
* Schema: add pole columns to `constraint_geo` (or a sibling table), keyed `(run_id, window_start, constraint_key)`.
* API: serve poles + field/top-K per constraint on `/map/*`.
* Web: diverging +/− SF choropleth for a selected constraint; dipole segments for the overview; SF=0 isoline for GTC/corridor; keep click-to-related-nodes. Load the `dataviz` skill before any render.
* Do NOT touch: the SF fit math (`fit.py`); the per-window walk-forward-honest derivation (geography stays honest, never a global SF).

## Acceptance

* [ ] A prototype renders the SF field / dipole / zero-isoline for representative constraints, including a bimodal GTC, from real data.
* [ ] `constraint_geo` (or sibling) carries the two poles + dipole strength per `(run_id, window_start, constraint_key)`.
* [ ] Overview renders oriented dipole segments, not overlapping centroids — no purple pile on bimodal constraints.
* [ ] Selecting a constraint renders a diverging +/− SF surface; a GTC/corridor shows the zero-isoline "cut".
* [ ] Geography stays walk-forward-honest (per-window SF only); click-to-related-nodes preserved; `dataviz` skill applied.
