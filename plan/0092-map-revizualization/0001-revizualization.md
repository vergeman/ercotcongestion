# 0001 - revizualization

Type: feat
Branch: feat/0092-0001-revizualization

> **Revised after the spike (2026-07-17).** The original plan replaced the single
> `|SF|`-weighted centroid with a signed **dipole** (two poles + axis). The spike
> (see `spike/` and `design-notes/`) showed that dipoles — and *any* per-constraint
> averaging — fail the real problem, which is the **all-constraints overview**: 1044
> constraints render as an indistinguishable purple pile because averaging pulls
> every constraint to the dense center of the state. The dipole primitive is
> **superseded**; the sections below are the validated design. The original
> dipole/pole text is preserved in git history.

## Goal

* Replace the single-centroid overview with a **de-piled, form-follows-type** map:
  each constraint is positioned at its **`|SF|²`-weighted geometric median** (its
  intensity *core*, which sits on the dominant lobe instead of averaging to the
  middle), and drawn with a mark whose *form* matches its *type*:
  * **GTC / interface** (contingency = `BASE CASE`) → a cluster-hugging **metaball
    "region shadow"** over its top-K nodes + a faint within-constraint **skeleton**
    tying its (often disjoint) pockets back to one core dot.
  * **transmission** (line + real contingency) → an **MST corridor** over its top-K
    nodes (short edges only), because these are co-located and a line reads right.
  * **radial / pocket** (rail signature) → a single **point**.
* Make the map navigable by **hover-isolate**: every settlement point is a
  deduplicated, hoverable dot; because a node belongs to many constraints, hovering
  opens a **membership popover** (each constraint it's in, tagged **source/sink** by
  signed SF, with severity) and clicking a row **isolates** that constraint (its
  footprint brightens, the rest ghost). Hovering a **core dot** isolates directly.
* Render a selected constraint's **drill-down** as the signed **source/sink field**
  (diverging blue = − / red = +) over its nodes — the one place sign is well-defined.

## Context

Findings from the spike, all against real `map-v1`, window `2025-11-04` (1044
located constraints). Data probes and renders live in `spike/`.

* **Averaging piles at the center.** The `|SF|`-weighted mean centroid lands within
  100 km of the state center for 50% of constraints (bimodal ones average their two
  lobes into the empty middle). The **`|SF|²` geometric median** cuts that to 15% —
  it snaps onto the strongest lobe. The raw peak node de-piles hardest (4%) but
  **collapses**: many constraints share a peak settlement point, stacking exactly on
  top of each other (1.4 km spacing). The `|SF|²` median is the sweet spot
  (continuous, 7 km spacing). See `spike/core_spike.py`.
* **All-1042 dipole chords / MST corridors are spaghetti** — median axis 263 km, so
  every line crosses the central knot. The fix is a **severity cut** (top-N by
  binding hours) + aggregation, not a cleverer glyph. See `spike/overview_spike.py`.
* **A node has no aggregate sign.** 100% of significant settlement points appear with
  *both* signs across different constraints. So the overview must **never** color by
  node sign; signed blue/red is reserved for the single-constraint drill-down.
  (`design-notes/type-coloring-and-sign.md`.)
* **Types are separable and cheap:** GTC 87 (15% of binding-hours), transmission 952
  (84%), radial 5 (1%), all from fields already persisted (`constraint_geo.n_rail`,
  `peak_offrail`, and the contingency string).
* **Membership popovers are readable:** among displayed nodes, memberships per node
  are median 1, mean 2.5, p90 5 (max 25 for rare hubs). See `spike/membership_probe.py`.
* **Colors reserved:** diverging **blue↔red** = signed SF in the drill-down only.
  Overview hues avoid blue/red — GTC **amber** `#e0a83a`, transmission **violet**
  `#a78bfa`, radial **teal** `#2dd4bf` (validated categorical separation).

## Approach

* **Data model shift — most of the original schema work falls away.** The render is
  **client-side** over the top-K node fields the API already serves. No persisted
  dipole/pole columns. What the API must add:
  * a **bulk overview endpoint** — for the top-N constraints by binding hours in the
    current window, return each constraint's `type`, `binding_hours`, `max_abs_sf`,
    the **`|SF|²` core** (lat/lon), and its **top-K nodes** (settlement_point, signed
    sf, lat/lon). One indexed slice per constraint; N and K are query params.
  * `/map/reach` already serves the single-constraint top-K signed field for the
    drill-down — reuse it.
* **Build order (own docs):**
  * **`0002-overview-core-and-type.md`** — the compute side: `constraint_core()`
    (Weiszfeld `|SF|²` geometric median) and `constraint_type()` in
    `compute/mu/geo.py`, persisted on `constraint_geo`, served by the bulk
    `/map/overview` endpoint (`api/map.py` + `api/models.py`). Pure derivation, no
    new fit — **`fit.py` and the per-window walk-forward derivation stay untouched**.
  * **web render doc (later)** — `web/src/api/types.ts` overview types and the
    `web/src/components/map/` render: metaball shadow via an SVG goo filter, MST
    corridors built client-side from top-K nodes, core markers, the node-membership
    popover, and hover-isolate. Reuse the diverging palette for the drill-down.
    **Load the `dataviz` skill before render work.**
* **Positioning stays walk-forward-honest:** the core and type derive from the same
  per-window honest SF as everything else; never a global fit.
* **Deferred (UI phase, own doc):** the browsable **side panel** — all members of a
  constraint, the source/sink lobe pairs laid out, synced hover with the map (also
  the overlap-proof way to reach any constraint). Noted, not built here.

## Acceptance

* [x] A prototype renders the overview + drill-down + interaction for representative
  constraints (incl. bimodal GTCs) from real data — `spike/` (interactive
  `hybrid4.html`).
* [ ] The overview positions each constraint at its `|SF|²` core (no central pile)
  and draws GTC region-shadows, transmission MST corridors, radial points, colored
  by type in non-reserved hues, sized by severity.
* [ ] Hovering a settlement point opens a membership popover (source/sink + severity,
  sorted by |SF|); clicking a row isolates that constraint; a core dot isolates
  directly; overlapping shadows never block picking.
* [ ] Selecting a constraint renders its signed source/sink field (diverging blue/red).
* [ ] Geography stays walk-forward-honest (per-window SF only); `dataviz` applied.
