# 0207 - misc-frontend-bugfixes

Type: fix
Branch: fix/0207-misc-frontend-bugfixes

## Goal

* Correct the Forecast map’s preview status at the Central-time delivery-day boundary.
* Remove the DetailCard reach-table scroll-through gap.
* Restore Brief hero-first, progressive loading and resolve all frontend lint findings.
* Condense curated-event copy without changing event identifiers, times, or views.

## Context

* `/forecast_range` keys `horizons` by CT `delivery_date`, but `getForecastHorizon()` currently keys lookup by the cursor’s UTC date. At 19:00 CST (18:00 CDT), that becomes the next UTC date, which can display the following day’s h2 badge over a settled ERCOT hour.
* The reach list’s sticky header sits after `.dc-drivers--reach` top margin/padding; its opaque header does not cover that spacer while rows scroll.
* Brief still has cached independent hero/standouts/details requests, but `globalLoading` hides all page chrome and content until the hero shell resolves. The prior progressive-loading plan intended a stable shell and hero-first reveal.
* ESLint’s JSON formatter exposes 26 frontend findings; its default `stylish` formatter crashes under local Node 18 because ESLint 10 calls unavailable `util.styleText`.

## Approach

### Commit 1 — make preview provenance CT-correct

* Work in: `web/src/api/prefetch.ts`, `web/src/features/map/useMapCursorData.ts`, and focused frontend coverage (or an extracted pure helper’s test).
* Use the existing CT formatter/day helper for `forecastHorizons` lookup; retain the backend’s CT `delivery_date` contract and the h1/h2 coalescing behavior.
* Cover a winter 19:00 CST cursor and summer 18:00 CDT cursor: an h2 next-day key must not mark the settled prior CT day as preview; the matching CT day still must show the badge.
* Do NOT touch: forecast cron timing, forecast persistence, or `/forecast_range` response schema.

### Commit 2 — seal the constraint-reach table header

* Work in: `web/src/components/map/DetailCard.tsx`, `web/src/components/map/detail/ReachBody.tsx`.
* Make the scroll container/header boundary continuous and opaque: move/replace the reach-list spacer so the sticky header’s surface covers every pixel where rows could pass, while preserving the section divider and current grid-column alignment.
* Verify a long reach list while scrolling on desktop and mobile: no map/background or node rows are visible between the preceding facts panel and `Settlement Point | SF | Contrib`.
* Do NOT touch: reach row cap, member interactions, contribution calculation, or card positioning.

### Commit 3 — restore Brief’s progressive shell

* Work in: `web/src/pages/BriefPage.tsx`, `web/src/features/brief/useBriefDay.ts`, `web/src/api/briefCache.ts`, and `web/src/features/brief/brief.css`.
* Keep the header and date controls mounted during initial/latest-day discovery and a day switch; reserve a lightweight hero frame instead of replacing the whole page with the centered loader.
* Retain cached request sharing and the current request sequence: fast hero shell plus standouts, then details only after the matching hero is available. Do not reintroduce bundled Brief or neighbor-detail fetches.
* Preserve stale-response guards, URL/cursor handoff, unavailable/error states, and per-panel loading states; make the hero the first meaningful content revealed.
* Add/extend browser-level coverage where available for cold load, direct date, and in-flight date switch; otherwise document the network/visual checks.

### Commit 4 — shorten event copy and clear the lint baseline

* Work in: `web/src/lib/events.ts`, `web/eslint.config.js`, and the reported frontend modules.
* Replace each active event `description` and `what_it_tests` with short, factual copy; keep IDs, labels, timestamps, and `suggested_view` unchanged.
* Resolve all current rule violations without blanket disables: unused matrix signal; stale-ref cleanup; unnecessary/missing hook dependencies; render-time ref reads; synchronous-effect state patterns in MiniMap, reach, picker, transport, Brief, Map, and shared explorer; and mixed component/helper exports in reach and scoreboard controls.
* Ignore generated Vite dependencies in ESLint and make `npm run lint` report normally on the supported project Node version; do not change lint rule severity merely to hide findings.

## Acceptance

* [ ] At 19:00 CST / 18:00 CDT, a settled CT delivery day never inherits tomorrow’s `Preview — refreshes at noon CT` badge; its real h2 day still displays it.
* [ ] Scrolling a long constraint reach list leaves no visible/translucent gap above the sticky column header on desktop or mobile.
* [ ] Brief displays stable chrome/date controls immediately, renders the hero before secondary sections, and does not block the page on the old global loading screen.
* [ ] Curated events are materially shorter with identical navigation data.
* [ ] `npm run lint` and `npm run build` pass in `web/` with no ESLint errors or warnings.
