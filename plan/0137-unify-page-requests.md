# 0137 - Unify page requests

Type: refactor
Branch: refactor/0137-unify-page-requests

## Goal

* Collapse the Brief page's per-day `/analysis/*` fan-out into one day payload.
* Merge the Scoreboard bootstrap trio into one summary payload.
* Merge the Map bootstrap quartet into one payload; leave interaction requests separate.
* Cut total requests per page load while keeping bootstrap and interaction fetches semantically exclusive.

## Context

* Brief fires ~8 requests per delivery day (hero/latest, hero, context, standouts, top-nodes, top-constraints, grade, grade-history), all keyed by the same `(deliveryDay, run)`.
* Scoreboard fires 3 (weekly, headline, daily); Map bootstrap fires 4 (topology, overview, meta, headline).
* Matrix already loads via a single `/matrix/frame` — no fan-out to reduce.
* Interaction-driven fetches (`/map/reach`, `/map/exposures`, hero prev/next prefetch) must stay their own calls — they fire on hover/click/navigation, not load.

## Approach

### Commit 1 — Brief day payload
* Add `/analysis/brief?day&run`: one response bundling the eight per-day sections currently served by `/analysis/hero|context|standouts|top-nodes|top-constraints|grade|grade-history`.
* Add `fetchBriefDayCached` in `web/src/api/briefCache.ts`; decode once, keep existing section shapes so consumers are untouched.
* Rewire `web/src/pages/BriefPage.tsx`: replace the per-section `useEffect` fetches with one day-payload effect; prev/next prefetch calls the same endpoint per day.
* Keep `/analysis/hero/latest` bootstrap as its own call (cursor discovery precedes the day fetch).

### Commit 2 — Scoreboard summary
* Add `/scoreboard/summary?regime`: weekly + headline + daily in one response.
* Rewire `web/src/pages/ScoreboardPage.tsx` to one fetch; preserve `weekly/headline/daily` sub-shapes.

### Commit 3 — Map bootstrap payload
* Add `/map/bootstrap`: topology + overview + meta + headline in one response.
* Rewire the four bootstrap `useEffect`s in `web/src/workspaces/MapWorkspace.tsx` to one.
* Do NOT touch `/map/reach`, `/map/exposures`, or `/map/constraints/ranked` — interaction/selection driven.

* Do NOT change Matrix; do NOT merge interaction fetches into any bootstrap payload.
* Keep the superseded single-section endpoints available until consumers are cut over, then remove in the same commit.

## Acceptance

* [ ] Brief load fires one day-payload request per rendered day, not eight.
* [ ] Scoreboard load fires one request, not three.
* [ ] Map bootstrap fires one request, not four; reach/exposures still fire per interaction.
* [ ] Matrix request count unchanged.
* [ ] Each merged payload preserves prior section shapes (no consumer-side reshaping).
* [ ] Compose API tests and web build pass.
