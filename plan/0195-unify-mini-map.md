# 0195 - unify-mini-map

Type: refactor
Branch: refactor/0195-unify-mini-map

## Goal

* Collapse the two lightweight SVG maps (`HeroMapPreview`, `BriefFootprintMap`) into one `MiniMap` component driven by a `mode` prop, with no change to what any of the three sites render.
* Delete the duplicated projection math, node-extraction, SVG scaffolding, and skeleton across the two files.
* Leave the interactive `/map` maplibre stack (`GridMap` and everything under it) completely untouched — out of scope.

## Context

* Three sites draw a small Texas outline + node scatter: the Brief hero backdrop, the Brief detail panel's "Grid footprint", and the `/matrix` Read side panel. `/map`'s `GridMap` is a separate maplibre-gl stack and is not part of this.
* The three sites are served by only two components today: `components/brief/HeroMapPreview.tsx` (hero) and `components/brief/BriefFootprintMap.tsx` (detail panel + matrix, already reused cross-feature).
* Duplication between the two:
  - **Projection.** `BriefFootprintMap` uses `lib/texasOutline.ts:fitBorderProjection`; `HeroMapPreview` re-implements the same lng-corrected projection inline (`HeroMapPreview.tsx:158-188`). `texasOutline.ts`'s own header comment already *claims* both share it — they don't.
  - **Node extraction.** Both independently `fetchTopology()` → `filter(isPoint)` → pull `sp_id/lng/lat`.
  - **SVG scaffolding.** Border `<path>` (evenodd, `--map-outline*` vars), skeleton-pulse CSS, and dot rendering are copy-pasted.
* The one real difference is the *data*: hero plots every node colored by LMP; footprint plots a constraint's SF-reach members (colored by SF) or a single located node. That difference becomes the `mode` switch, not two components.
* Naming smell being fixed in passing: `BriefFootprintMap` lives in `components/brief/` but is imported by `components/matrix/MatrixReadDetail.tsx`. The unified component moves to a neutral `components/map/`.

## The unified component

`components/map/MiniMap.tsx` — one component, discriminated-union props by `mode`:

```
mode "lmp"        { mode; cursor: {t;ws;we}; basis: "forecast"|"settled" }
mode "constraint" { mode; selectionKey; mapHref; t?; onNavigate?; showTitle?;
                    reach?; reachLoading? }
mode "node"       { mode; selectionKey; mapHref; t?; onNavigate?; showTitle?;
                    nodeLocation? }
```

* `mode: "lmp"` reproduces `HeroMapPreview` exactly: decorative (`aria-hidden`), no chrome, height-anchored fit with a right-pinned dynamic width (`xMaxYMid meet`), fetches settled/forecast hour values with the existing fallback, colors dots via `lmpColor`/`computeLmpStats`/`normalizeLmpFromStats`, fails silently to no frame.
* `mode: "constraint"` and `mode: "node"` reproduce `BriefFootprintMap`'s two `geo` branches: `role="img"` + aria-label, optional "Grid footprint" title, the bottom-right "Open in Map →" link (with the plain-vs-modified-click `onNavigate` interception), `meet`/centered fit at 320×200, unavailable states, focus ring. `constraint` colors by `shiftFactorColor`; `node` uses `--accent` + focus ring. The provided-reach (Matrix) vs fetched-reach (Brief `useConstraintReach`) distinction is preserved.
* Naming: modes use `constraint`/`node` to line up with `BriefSelectionGeo` (`lib/briefSelection.ts`), so call sites map `geo` → `mode` with no translation. (The earlier sketch said "reach"; `constraint` avoids a vocab fork.)
* Internal structure to keep the fat component honest: one shared presentational core (border path + projected dots + skeleton) rendered by every mode; mode selects only the data branch, the fit config, and whether chrome is drawn. Both style blocks (`.hero-map*`, `.bfm*`) travel with the component, selected by a variant class.

## Approach

* Work in: `lib/texasOutline.ts`, NEW `components/map/MiniMap.tsx`, `components/brief/BriefHero.tsx`, `components/brief/BriefDetailPanel.tsx`, `components/matrix/MatrixReadDetail.tsx`. Delete `components/brief/HeroMapPreview.tsx` and `components/brief/BriefFootprintMap.tsx`.
* Extend `fitBorderProjection` with a fit option so the hero's inline projection can be deleted: `fitBorderProjection(rings, { width, height, pad, fit })` where `fit: "meet"` (default, footprint) | `"fillHeight"` (hero: anchor scale to height, compute width from span, caller right-pins via `preserveAspectRatio`). Return `{ project, borderPath, width, height }`. Keep the existing positional signature working for `BriefFootprintMap`'s call, or update that call in the same pass.
* Add `settlementPointsFromTopology(topology)` → `{ sp_id, lng, lat }[]` to `texasOutline.ts`; use it in the `lmp` branch (all points) and the `node` branch (find by key). Removes the duplicated `isPoint` extraction.
* Re-point the three call sites:
  - `BriefHero.tsx`: `<HeroMapPreview cursor basis/>` → `<MiniMap mode="lmp" cursor basis/>` (keep the `!mobile && hero.cursor` guard).
  - `BriefDetailPanel.tsx:659`: `<BriefFootprintMap selection={{geo,key}} mapHref t=/>` → `<MiniMap mode={geo} selectionKey={key} mapHref t/>`.
  - `MatrixReadDetail.tsx:301,569`: the constraint and node `<BriefFootprintMap>` → `<MiniMap mode="constraint" .../>` and `<MiniMap mode="node" .../>`, carrying `onNavigate`, `showTitle={false}`, `constraintReach`/`nodeLocation` as today.
* Keep behavior byte-for-byte per site: same fetches, same colors, same fallbacks, same chrome, same aria. This is a move + merge, not a redesign.
* Do NOT touch: `GridMap.tsx`, `overviewSources.ts`, `useSynchronizedMaps.ts`, `DetailCard.tsx`, `Legend.tsx`, `MapWorkspace.tsx`, or any `/map` code; the `/texas.geojson` asset; the LMP/SF color math in `lib/colors.ts`.

## Verification

* No web unit-test framework exists (no vitest/jest, no `test` script). Verify with `tsc -b` (typecheck) and `eslint .` in `web/`.
* Do NOT run the full `build` — it ends in `vite build`, which the local Node 18 can't complete (see memory). `tsc -b` typecheck is the ceiling locally.
* Manual smoke on a dev server if available: hero backdrop still paints, detail-panel footprint + "Open in Map" still work, matrix Read panel constraint and node maps still render.

## Acceptance

* [ ] Exactly one mini-map renderer: `components/map/MiniMap.tsx`; `HeroMapPreview.tsx` and `BriefFootprintMap.tsx` are deleted.
* [ ] Projection lives once (`fitBorderProjection` with a fit option); no inline projection remains.
* [ ] Node extraction lives once (`settlementPointsFromTopology`).
* [ ] All three sites render identically to before (hero backdrop, brief footprint, matrix Read constraint + node), including colors, chrome, aria, and fallbacks.
* [ ] No `components/brief/*` import survives in `components/matrix/`.
* [ ] `/map` (`GridMap` and its stack) is unchanged.
* [ ] `tsc -b` and `eslint .` pass in `web/`.
