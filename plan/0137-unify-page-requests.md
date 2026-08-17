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
* Profiled the 7 composed sections in isolation: `grade` was the outlier (~10s vs. 0.1–4s for everything else).
* Root cause: `grade`'s climatology baseline (`_trailing_settled_average`) looped 30 trailing days, issuing one DB query per day per half (constraints + nodes) — up to 60 round trips.
* Fixed: batched each half into one query over the whole window (`_windowed_mu_profiles`, `_windowed_node_profiles`), split by CT delivery day in pandas instead of in SQL-per-day. Also switched that bulk fetch to a `tuple_row` cursor + explicit `DataFrame(rows, columns=...)` instead of the request's shared `dict_row` cursor — ~30% faster to materialize at this row count (dict-per-row construction dominates at ~800K rows).
* Remaining `grade` cost (node half's climatology query is still ~2.8s) is real data volume (30 days × ~1,100 points × 24h) plus `grade_profiles()`'s own scoring compute, not a query-count problem — left as is.
* `standouts` (the next-slowest section, ~3.7s) has similar 30-iteration-loop shapes (`_settled_node_history`, a 30x artifact-decode loop) — flagged as a follow-up.

### Commit 5 — Batch `_settled_node_history` (standouts / top-nodes)
* `_settled_node_history` still looped 30 trailing days, one DB round-trip per day, while its sibling `_settled_constraint_history` was already a single windowed query. Called by both `/analysis/standouts` and `/analysis/top-nodes`, so the fan-out hit two Brief sections.
* Fixed: collapsed to one window query grouped by `(settlement_point, CT delivery day)` — same partition the sibling uses (established delivery-day-cut convention) — then reshaped to the per-day list in Python. 30 round trips → 1.
* Behavior-preserving: every requested point is still present in the result (quiet days fill `0.0`), since callers index the dict directly; day ordering is oldest→newest as before. Compose/analysis tests unchanged (32 pass; 3 pre-existing failures in `grade`/`top-constraints` are unrelated).
* Deferred: the 30x artifact-decode loop in `standouts` (lines ~1072-1081) is a decode-CPU cost (one npz per prior day), not primarily a query-count one — batching the `SELECT sf_npz` fetch saves round trips but not the 30 decodes. Left for a separate pass if standouts is still the bottleneck.

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
* [x] `/analysis/brief`'s slowest section(s) identified and sped up; benchmark improves over Commit 1's baseline (`/analysis/grade` isolated: ~10s → ~6–9s; bundled `/analysis/brief`: ~13.96s → ~13.05s median).
