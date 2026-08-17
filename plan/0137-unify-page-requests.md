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

### Commit 3 — Map summary payload
* Add `/map/summary`: topology + overview + meta + headline in one response. (Shipped as `/map/bootstrap`, renamed to `/map/summary` post-review for naming consistency with `/scoreboard/summary` — see Implementation notes.)
* Rewire the four bootstrap `useEffect`s in `web/src/workspaces/MapWorkspace.tsx` to one.
* Do NOT touch `/map/reach`, `/map/exposures`, or `/map/constraints/ranked` — interaction/selection driven.

### Commit 4 — Speed up /analysis/brief's slow sections
* Profile the 7 composed sections (hero, context, standouts, top-nodes, top-constraints, grade, grade-history) to find which one(s) dominate the ~14s wall-clock cost seen in benchmarking.
* Prime suspect: per-day-in-a-loop history queries (`_settled_node_history`, `_trailing_settled_average`, and similar 30-iteration loops) issuing one DB round-trip per day instead of one batched query.
* Rewrite the worst offender(s) to a single query over the window; re-run the Commit 1 benchmark to confirm.

* Do NOT change Matrix; do NOT merge interaction fetches into any bootstrap payload.
* Keep the superseded single-section endpoints available until consumers are cut over, then remove in the same commit.

## Implementation notes

* Sections are composed in-process (plain function calls, not HTTP fan-in) — every param needs an explicit literal, since a default falls through as a raw `Query(...)` object. Bit us once in `get_context`; fixed and test-covered.
* Composed sections run in a `ThreadPoolExecutor`, not sequentially — sequential cost ~20% more wall-clock than the old fan-out (benchmarked), since it forfeits FastAPI's per-request threadpool concurrency.
* `/map/bootstrap` renamed to `/map/summary` (matches `/scoreboard/summary`).
* Single-section endpoints were kept (composed endpoints call them internally); only now-unused frontend fetch wrappers were deleted.
* Scoreboard's `daily` board is no longer regime-independent-cached — it re-fetches (same result) on every regime change now. Accepted tradeoff.
* `/scoreboard/*` and `/map/*` soft-fail per section via a `_soft_fail` 503→null helper; `/analysis/*` didn't need one (already typed `available: false`).

## Acceptance

* [x] Brief load fires one day-payload request per rendered day, not eight.
* [x] Scoreboard load fires one request, not three.
* [x] Map summary fires one request, not four; reach/exposures still fire per interaction.
* [x] Matrix request count unchanged.
* [x] Each merged payload preserves prior section shapes (no consumer-side reshaping).
* [x] Compose API tests and web build pass.
* [ ] `/analysis/brief`'s slowest section(s) identified and sped up; benchmark improves over Commit 1's baseline.
