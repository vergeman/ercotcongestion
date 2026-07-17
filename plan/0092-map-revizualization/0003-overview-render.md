# 0004 - overview render (web side)

Type: feat
Branch: feat/0092-0003-overview-render

> The web build for the revizualized overview. Consumes `0002`'s `/map/overview`
> endpoint. Design of record: `0001-revizualization.md`; the validated prototype is
> `spike/renders/overview-interactive.html`. **Load the `dataviz` skill before any
> render work.**

## Goal

* Replace the flat `|SF|`-mean centroid overlay (the purple pile of X's from
  `/map/constraints`) with the **de-piled, form-follows-type** overview: every
  constraint at its `|SF|²` **core**, drawn with a mark chosen by `ctype` and
  colored in a non-reserved hue, sized by severity.
* Make it navigable by **hover-isolate** + a **node-membership popover**, and keep
  the existing single-constraint **drill-down** (signed reach) unchanged.

## Context — the one real architectural decision

The map is **maplibre-gl (WebGL)**; the current constraint overlay and the reach
dipole are native maplibre GeoJSON `circle`/`line` layers (`GridMap.tsx`). But the
prototype's core mark for a GTC is a **metaball "goo" shadow** — an SVG
`feGaussianBlur` + `feColorMatrix` alpha-threshold filter — which maplibre's WebGL
layers **cannot** render. The MST corridors, core dots, and the membership popover
are also easiest as vector SVG with real hit-testing.

**Decision: render the overview as an SVG overlay pinned over the maplibre canvas**,
projecting lat/lon → screen with `map.project()` and re-drawing on every
`move`/`zoom` (the same camera the panes already mirror). The maplibre basemap, city
labels, and SP layer stay beneath; the overview SVG rides on top. This is exactly
what the spike did, so the goo filter, MST, hover-isolate, and popover port directly.
Native maplibre layers were considered and rejected: a `heatmap` layer approximates
the goo but loses the crisp cluster-hugging edge and can't carry the skeleton or the
per-mark hit-testing the isolate interaction needs. (Revisit only if the overlay's
camera-sync redraw is too costly at N=70 — it was not in the prototype.)

## Approach — staged commit units

* **A — data plumbing.** `web/src/api/types.ts`: `MapOverview` / `OverviewConstraint`
  (nodes reuse `ReachSp`), mirroring `api/models.py`. `web/src/api/client.ts`:
  `fetchMapOverview(n, k)` with the same soft-fail contract as the other `/map/*`
  fetchers. No render yet.
* **B — the de-piled base layer.** An SVG overlay component synced to the maplibre
  camera; **core dots** at `core_lat/core_lon`, colored by `ctype` (amber `#e0a83a`
  gtc / violet `#a78bfa` transmission / teal `#2dd4bf` radial), radius by severity
  (`binding_hours` or `max_abs_sf`). This alone must show *no central pile*. The
  dots are the **hit targets** (`pointer-events` on the discrete points).
* **C — form-follows-type marks** (passive layers beneath the dots,
  `pointer-events: none`):
  * **gtc** → metaball **region-shadow** over its top-K nodes via the SVG goo filter,
    plus a faint **skeleton** (thin lines from each node to the core) tying disjoint
    pockets to one dot.
  * **transmission** → an **MST corridor** built client-side (Prim over haversine,
    drop edges > 150 km) across its top-K nodes.
  * **radial** → just the core **point**.
* **D — interaction.**
  * **hover-isolate**: hovering a core dot (or a membership row) brightens that
    constraint's footprint and ghosts the rest; overlapping shadows never block
    picking because only the dots are hit targets.
  * **node-membership popover**: settlement points are deduplicated into hoverable
    dots; hovering one opens a popover listing every overview constraint it belongs
    to, tagged **source/sink** by its signed SF and sorted by `|SF|`; clicking a row
    isolates that constraint. (Readable: median 1 / p90 5 memberships,
    `spike/membership_probe.py`.)
  * **drill-down** stays the existing `/map/reach` signed field (diverging
    blue = − / red = +) — the one place sign is well-defined. Selecting from the
    overview (dot or popover row) drives it.
* **E — legend + accessibility pass.** Update `Legend.tsx` for the three type marks;
  run `dataviz` palette validation on the overview hues (light + dark surfaces);
  ensure identity is never color-alone (the *form* already carries type); dark mode
  stepped, not flipped; a table/list fallback for the overview set.

## Acceptance

* [ ] The overview replaces the centroid pile: constraints sit at their cores, no
  central knot; gtc region-shadows, transmission MST corridors, radial points,
  colored by type in non-reserved hues, sized by severity.
* [ ] Hovering a core dot isolates its constraint; overlapping gtc shadows never
  block picking (dots are the only hit targets).
* [ ] Hovering a settlement point opens a membership popover (source/sink + severity,
  sorted by `|SF|`); clicking a row isolates that constraint.
* [ ] Selecting a constraint renders its signed source/sink drill-down (diverging
  blue/red), unchanged from today.
* [ ] `dataviz` applied: overview palette validated (light + dark), legend present,
  type conveyed by form + hue (never hue alone), table fallback exists.
* [ ] Camera-synced redraw stays smooth at N=70; `npm run build` + lint clean.

## Deferred (own doc, UI phase)

The browsable **side panel** — all members of a constraint, the source/sink lobe
pairs laid out, synced hover with the map (also the overlap-proof way to reach any
constraint). Noted in `0001`; not built here.
