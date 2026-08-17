# 0135 - brief detail panel

Type: feat
Branch: feat/0135-brief-detail-panel
Depends on: `0129-0009`
Status: complete

## Goal

* Add one shared sliding detail panel for Standouts and selectable Top Constraints / Top
  Nodal Congestion rows.
* Let a reader orient the selected element on a small abstract map, inspect the evidence
  behind the row, then deliberately open the full Map from the panel.

## Context

* A Brief table row is an inspection action, not a direct navigation link. Direct links
  make the reader leave the brief before they understand why an item ranked.
* The full interactive Map remains `/map`. The panel map is deliberately small and
  abstract: geolocation/footprint for orientation, not a second Map workspace or a
  second playback transport.
* `0129-0009` owns mode detection and every main-page forecast-only/post-settle rendering
  decision. This plan only consumes that already-selected mode (`settled`) to avoid
  showing unavailable evidence in the panel.

## Deviation from the original plan

The original draft deferred the Map handoff (kept the row `/map` links, waited on
`0130-map-views-and-link`). During implementation this was overridden: **rows are no
longer links** — they open the panel — and the **Map handoff link moved into the panel**,
built from the existing `0131` deep-link contract (`buildMapLink`, Forecast × Congestion,
no autoplay). The handoff is therefore implemented here, not deferred.

## What was built

### Selection model — `web/src/lib/briefSelection.ts`
Discriminated union `BriefSelection` over the four row schemas
(`standout-constraint` | `standout-node` | `constraint` | `node`) plus:
* `selectionGeo` → `constraint | node` (the axis the footprint + Map link key off),
* `selectionMapTarget` / `selectionIdentity` / `selectionKey`,
* `briefElementMapHref(heroCursor, selection)` — the moved-from-the-row Map link.

### Shared formatters — `web/src/components/brief/briefFormat.tsx`
`usd`, `percent`, `zoneLabel`, `constraintName`, `rankMovement`, and the
`HistoryWhisker` / `HistoryBars` glyphs, extracted from `BriefPage` so the panel and the
tables render identically from one source. Two shared-glyph fixes fell out of this work
and benefit the Brief tables too:
* `HistoryWhisker` plots today's mark even when the p10–p90 band is null (was returning
  a blank em dash), so model-only resource nodes still show today.
* `HistoryBars` became a **signed** diverging chart (zero baseline, bars up for positive /
  down for negative), fixing the Brief tables' inline bars for import nodes whose daily
  congestion is negative — they previously collapsed to a 2px floor.

### Shared constraint-reach primitives — `web/src/components/panels/ConstraintReach.tsx`
Extracted from the map's `ConstraintPanel` and reused by BOTH the map sidebar and the
Brief panel: `useConstraintReach` (fetch + module cache, shared across surfaces),
`MemberList` / `Membership`, `Dipole` / `dipoleCounts`, `SfDipoleLegend`, `fmtMag`,
`ConstraintReachStyles`. Member SF renders at **3 decimals**, consistent with the map's
`DetailCard`.

### Shared Texas outline — `web/src/lib/texasOutline.ts`
`loadTexasBorderRings` + `fitBorderProjection`. `HeroMapPreview` was refactored to use it
(dropping its private copy), so the hero preview and the footprint share one loader.

### The panel — `web/src/components/brief/BriefDetailPanel.tsx`
* Portaled to `document.body`; scrim + panel are **permanently mounted** and slide via an
  `--on` class **CSS transition** (no mount-time `@keyframes`, which flashes the final
  frame — the FOUT). `rendered` state keeps the last selection so the panel keeps its
  content while sliding out.
* Dialog semantics: `role="dialog"`, focus trap, focus-to-close on open, focus return on
  close, Escape close, backdrop (scrim) close, page scroll-lock while open.
* Opening/closing never rewrites `?t / ?ws / ?we`.
* Consumes `0009`'s `settled` mode: settled evidence columns render only once settled.
  In a t+2 preview horizon the basis chip reads **"Forecast"** (basis stays forecast
  until DAM clears); it becomes **"DAM settled"** only after settlement.
* Header: constraint name + contingency (lighter grey, no `|`) / node id; basis chip
  under the title on the left; close button top-right.
* Evidence as a minimal headerless label→value list (fixed label column, left-aligned
  values).
* 30-day history: full-width whisker with p10 / p90 printed above the line and today
  below it (labels pinned to their true points). Today's mark always plots — the p10–p90
  band is optional, so a model-only resource node (`_UNIT` / `_RN`, no published settled
  prices) still shows today rather than a blank whisker.
* The per-day bars are a **signed** diverging chart (`SignedBars`): each of the trailing
  30 settled days plus today (appended, highlighted) grows up (positive / export) or down
  (negative / import) from a zero baseline, with a left y-axis showing the true min/max.
  This is required for import nodes, whose daily congestion is negative — the earlier
  magnitude-from-bottom bars collapsed those to an invisible floor.
* Grid reach: dipole + located member list + one-per-line SF legend, from the shared
  `useConstraintReach`.

### The footprint — `web/src/components/brief/BriefFootprintMap.tsx`
Small non-interactive orientation map: a constraint paints its located SF-reach members
(import/export coloured); a node paints its single located point. Honest
unavailable-location state (a hub / aggregate with no coordinate says so). The
"Open in Map →" action is a control ON the map (bottom-right); there is no separate
bottom action panel.

### `BriefPage.tsx`
The four ranked/standout row cells are `<button class="an-row-link">` triggers that open
the panel; the per-row `/map` links and the duplicated helpers were removed. The Top
Nodal Congestion header labels were tightened for width: `COVERAGE → COV`,
`7×16 $/MWh → Peak` (Standouts' node table keeps its original labels).

## Incidental fix (backend)

While closing this out, `/analysis/standouts` was found to 500 on every day — a
**pre-existing** bug from commit `2b6c7d1` (Fix/0132), unrelated to this front-end work:
`api/analysis.py` dereferenced `prior.profile` where `_forecast_node_profile()` returns a
bare `DataFrame`. Fixed to `prior` (one line). This should be committed separately from
the panel work.

## Acceptance

* [x] Each Standout and selectable row in both ranked tables opens the same detail panel;
      none is a direct navigation link.
* [x] The panel has correct keyboard behavior, dialog semantics, focus return, close
      control, Escape close, and backdrop close.
* [x] Opening and closing it leaves the Brief URL time coordinate unchanged.
* [x] The panel consumes 0009's selected mode and never makes a second availability
      decision or renders unavailable settled evidence.
* [x] The abstract map is geolocated when data exists, remains lightweight, and has an
      honest unavailable-location state.
* [x] The Map handoff lives in the panel (rows are not links). Built from the 0131
      deep-link contract; the original "leave `/map` links unchanged" condition was
      superseded by explicit direction.
* [x] The panel slides (CSS transition, both directions) with no flash-of-unstyled-content
      and dims the page behind a scrim.
* [x] Shared constraint-reach primitives and the Texas outline are used by both the map
      surfaces and the Brief panel (no duplicated fetch/cache/glyphs).
* [x] Evidence reads as a minimal label→value list; grid-reach SF at 3 decimals (map
      parity); grid-reach legend one colour per line, no larger than section titles.
* [x] 30-day history: whisker prints p10/today/p90 pinned to their points and always
      shows today; per-day bars are signed (up/down from zero) with a left y-axis — in
      both the panel and the Brief tables' inline glyphs.
* [x] "Open in Map" is a control on the footprint map (no bottom action panel); Top
      Nodal Congestion headers tightened (`COV`, `Peak`).
* [x] `tsc --noEmit -p web/tsconfig.app.json` clean.

## Verification

`tsc` clean in the `web` container (local Node cannot build). Behavior confirmed in
headless Chrome (puppeteer): row-click opens the panel under `<body>`; scrim dims the
page and is the topmost layer; scrim-click, Escape, and the close button all close;
focus moves into the panel and the page scroll locks; the footprint renders located
members with real coordinates.
