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
* Collapsed the 30-round-trip per-day loop into one window query grouped by `(settlement_point, CT delivery day)`, mirroring its already-batched sibling `_settled_constraint_history`. Behavior-preserving (all points present, quiet days `0.0`, oldest→newest).

### Commit 6 — Standouts artifact loop: cache budget + batched fetch (Option 2)
* After Commit 5, `standouts` was the sole slow section: **3.86s, never warms** (combined `/brief` ~5.6s). cProfile: the 30x prior-day `_forecast_node_profile` loop = 2.9s (~0.7s round trips + ~1.4s npz decode). It never warms because a call touches 31 artifacts against a 128 MiB LRU (~28 slots) → thrash.
* Fix (api-only): raised `ARTIFACT_CACHE_MAX_BYTES` 128→256 MiB (31-artifact window now fits), and added `load_daily_artifacts` — one windowed `SELECT ... = ANY(%s)` for cache misses vs. 30 round trips (`_project_node_profile` factored out to share the projection).
* Result: standouts cold ~3.8s, **warm ~1.3s** (was 3.86s flat); combined `/brief` ~4.3s. Behavior-preserving; tests unchanged (same 3 pre-existing failures).

### Concurrency finding — the real reload cost
* Commit 6 helped the single warm request, but a browser **reload fires 3 `/brief` concurrently** (current + prev/next prefetch). Each brief runs 7 sections × 1 connection in a threadpool; 3 briefs = 21 checkouts against a `max_size=8` pool + GIL-bound pandas → reload 10–17s (measured 8/9/15s, and the "warm" retry *worse*). Per-request query tuning can't touch this.

### Commit 7 — Defer neighbor prefetch (frontend, #1)
* `BriefPage.tsx` fired the prev/next full-`/brief` prefetch **concurrently** with the current day (two effects, same deps), so the visible day raced two heavy prefetches. Moved the prefetch into the current-day fetch's `.finally` so it runs **after** the day resolves — current day renders on a clear critical path; neighbors warm the cache/enable carets in the background. Reload critical path ~15s → ~current-day-solo (~4–5s).

### Commit 8 — Thread-safe artifact cache (backend, #2)
* `SfArtifactCache` (`OrderedDict`) had no lock; concurrent `standouts` across the composed threadpool(s) raced `get`/`put`/evict → redundant decodes and inconsistent hits (why the warm retry was slower). Guard the ops with a `threading.Lock`.

### Commit 9 — Settled-day `/brief` response cache
* Cache the composed `BriefDayResponse` by `(run_id, day, horizon)` to skip the per-section pandas (~4s) the artifact cache can't touch. In-process count-bounded LRU (small payloads), lock-guarded. Settled `/brief` **~4.4s → ~6ms**.
* Gate `_brief_is_final`: the Brief reads only day-ahead DAM (never revised), so a day is immutable once `horizon == 1`, strictly past in CT, and `_dam_landed`. Live/preview/DAM-pending days recompute — nothing live is served stale. Two tests added.
* Dev caveat: dev DAM is stale (~5 days back), so the newest 1–2 days aren't cached there; prod DAM tracks day-ahead → whole history caches.

### Deferred
* Option 1 (parallel decode) was prototyped (cold ~2.7s) but **cut** — Option 3 supersedes it.
* Uncached (live/newest) days stay decode-floored; the real fix is precompute — see `plan/0138-forecast-nodal-live-daily.md` (daily `forecast_nodal` table; standouts → ~0.3s, so even a cold brief is ~1s).
* Optional: in-flight decode dedup (coalesce concurrent cold loads of the same artifact) for the rare case that duplicate cold requests still race.

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
