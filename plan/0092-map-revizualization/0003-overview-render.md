# 0003 - overview render (web side)

Type: feat
Branch: feat/0092-0003-overview-render

> The web build for the revizualized overview. Consumes `0002`'s `/map/overview`
> endpoint. Design of record: `0001-revizualization.md`. The **reference of record is
> the interactive spike `spike/build_hybrid4.py`** (hybrid-v4) — the overview overlay
> is a faithful React/SVG port of it, so match its marks and interaction directly
> rather than reinterpreting. **Load the `dataviz` skill before any render work.**

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

* **A — data plumbing. ✅ done.** `web/src/api/types.ts`: `MapOverview` /
  `OverviewConstraint` (nodes reuse `ReachSp`), mirroring `api/models.py`.
  `web/src/api/client.ts`: `fetchMapOverview(n, k)` with the same soft-fail contract
  as the other `/map/*` fetchers.
* **B — the de-piled base layer. ✅ done** (superseded by C+D). Shipped first as
  plain **core dots** at `core_lat/core_lon`, colored by `ctype`, sized by severity —
  enough to prove *no central pile*, but only a stepping stone; the marks and
  interaction below replace the bare dots.
* **C + D — faithful hybrid-v4 port. ✅ done (one unit).** The first pass at C/D
  diverged from the spike (invented marks, no visible metaball/MST, click routed to
  the `DetailCard`, a stray reach dipole). It was rejected and rebuilt: `OverviewOverlay.tsx`
  is now a direct port of `spike/build_hybrid4.py`. **C and D are inseparable in the
  reference** — the marks *are* the hit targets — so they land together. Fetched at
  **k = 6** to match the spike's region density (k = 16 bloats the goo into one cloud).
  * **form-follows-type marks** (passive, `pointer-events: none`; draw order
    gtc → transmission → radial):
    * **gtc** → metaball **region-shadow** over its nodes via the SVG goo filter
      (`feGaussianBlur` + alpha-threshold `feColorMatrix`), blob radius ∝ √|SF|, plus a
      faint **skeleton** (the MST, thin).
    * **transmission** → an **MST corridor** built client-side (Prim over haversine,
      dropping edges > 150 km) — ported from `spike/mst_spike.py`.
    * **radial** → a hollow core **ring**.
  * **hover-isolate**: each constraint carries a transparent core **hit target**;
    hovering it (or a popover row) brightens that constraint and ghosts the rest
    (`svg.dim`). Overlapping shadows never block picking — only the hit targets and
    node dots opt back into `pointer-events`.
  * **node-membership popover**: settlement points are deduplicated into hoverable
    dots; hovering one opens a **cursor popover** listing every overview constraint it
    belongs to, tagged **source/sink** by signed SF and sorted by `|SF|`. Hovering a
    row isolates; **clicking a row pins** that isolation (median 1 / p90 5 memberships,
    `spike/membership_probe.py`). Clicking bare canvas clears the pin.
  * **self-contained interaction — decoupled from the legacy drill-down.** The
    overview's own hover-isolate + popover *replace* the old constraint-click path; it
    no longer drives `/map/reach`, the `DetailCard`, or the dashed **reach-corridor**
    arc (that stray dotted line was the confusing symptom of the first divergence).
    The signed reach dipole stays available for the base SP-layer flow but is not what
    the overview surfaces.
* **E — legend + accessibility pass.** ⬜ next. Update `Legend.tsx` for the three type
  marks (the legend still reads the old "SIZE ∝ MAX |SF|"); run `dataviz` palette
  validation on the overview hues (light + dark surfaces); ensure identity is never
  color-alone (the *form* already carries type); dark mode stepped, not flipped; a
  table/list fallback for the overview set.

## Acceptance

* [x] The overview replaces the centroid pile: constraints sit at their cores, no
  central knot; gtc region-shadows, transmission MST corridors, radial points,
  colored by type in non-reserved hues, sized by severity.
* [x] Hovering a core dot isolates its constraint; overlapping gtc shadows never
  block picking (dots are the only hit targets).
* [x] Hovering a settlement point opens a membership popover (source/sink + severity,
  sorted by `|SF|`); hovering a row isolates and clicking a row pins that constraint.
* [x] The overview interaction is self-contained: it does **not** trigger the legacy
  `/map/reach` dipole, `DetailCard`, or the dashed reach-corridor arc.
* [ ] `dataviz` applied: overview palette validated (light + dark), legend present,
  type conveyed by form + hue (never hue alone), table fallback exists. *(unit E)*
* [x] Camera-synced redraw stays smooth at N=70; `tsc -b` + `OverviewOverlay` lint clean.

## Deferred (own doc, UI phase)

The browsable **side panel** — all members of a constraint, the source/sink lobe
pairs laid out, synced hover with the map (also the overlap-proof way to reach any
constraint). Noted in `0001`; not built here.
