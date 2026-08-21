# 0155 - brief progressive loading

Type: refactor
Branch: refactor/0155-brief-progressive-loading

## Goal

* Render a usable Brief shell and delivery-date control immediately, with no stray “Load Window” affordance.
* Deliver the hero and day-navigation metadata ahead of the secondary Brief sections.
* Measure and reduce the slowest uncached Brief-detail work without reintroducing competing neighbor loads.

## Context

* `BriefPage` currently waits for `/analysis/hero/latest`, then blocks all visible Brief content on one seven-section `/analysis/brief` response; section-level loading flags cannot produce progressive rendering because the payload resolves atomically.
* The date picker is already configured as `singleDate`, but it is hidden until discovery completes and its icon still carries the inherited “Load window” control language.
* Plan 0137 measured current + neighbor full-Brief concurrency as the source of 10–17 s reloads; deferred neighbor prefetch improved the critical path, but it is still unnecessary work merely to enable the carets.
* Settled full Briefs have an in-process cache; newest, preview, and DAM-pending days remain uncached, so their detail queries need an explicit baseline before tuning.

## Approach

### Commit 1 — establish the uncached-detail baseline

* Work in: `api/analysis.py`, `api/tests/test_analysis.py`, and a documented dev benchmark command under `api/tests/README.md`.
* Time the composed Brief sections independently and the whole request for representative settled-cache-miss, newest/forecast, and DAM-pending days; record wall time, query count, and cache state.
* Capture `EXPLAIN (ANALYZE, BUFFERS)` for the slowest SQL paths, beginning with the repeated 30-day DAM-history scans in `get_standouts`, `get_top_constraints`, `get_top_nodes`, `get_context`, and grade history.
* Add narrowly scoped timing instrumentation to the new detail composition path (section name plus elapsed time); expose it only in development/test or slow-request logs, never as user-visible content or a permanent per-query production log stream.
* Use the measurements to select only behavior-preserving fixes: share duplicate trailing-history/geography reads within one request, add a verified missing index, or reuse an existing daily materialization. Do not guess at an optimization before the query plans identify it.

### Commit 2 — split the fast Brief shell from secondary detail

* Work in: `api/analysis.py`, `api/models.py`, `api/tests/test_analysis.py`, `web/src/api/client.ts`, `web/src/api/briefCache.ts`, and `web/src/api/types.ts`.
* Add a lightweight `GET /analysis/brief/hero?day&run` response that returns the existing hero shape plus the nearest previous/next artifact-backed delivery dates for the same resolved run. Resolve the run and horizon once; use bounded date lookups, not `/brief` prefetches, for the carets.
* Add `GET /analysis/brief/details?day&run` for context, standouts, top constraints, top nodes, grade, and grade history. Preserve each section’s current schema and run those independent sections in the existing bounded server-side composition.
* Split the existing settled-day cache into immutable hero-shell and detail entries keyed by `(run_id, day, horizon)`, retaining the finality guard. Coalesce or cache only identical requests; do not cache preview or DAM-pending data as final.
* Retire `BriefPage`’s use of the monolithic `/analysis/brief` and its current/previous/next full-payload prefetch. Keep the legacy bundled endpoint temporarily only if another consumer exists; otherwise remove it with its dedicated tests in this commit.
* Add API tests proving hero-shell navigation dates do not invoke detail handlers, detail composition excludes hero work, final-day cache behavior remains correct, and unresolved/artifact-missing days retain the present unavailable shape.

### Commit 3 — make the loading experience a stable, date-first shell

* Work in: `web/src/pages/BriefPage.tsx`, `web/src/components/playback/DateRangePicker.tsx`, and the Brief’s page-local styles/tests.
* Mount the Brief header, delivery-date field, calendar trigger, and date selection popover on first paint. Rename the inherited trigger/accessibility copy to “Choose delivery date” (or equivalent date language); never show “Load Window” on the Brief.
* Treat the date as a page parameter: a URL day is actionable immediately; on cold entry use the inexpensive hero-shell latest-day discovery only to populate a default, without withholding the date control. A user can choose a date while the default or any data request is pending.
* Render a deliberate empty page frame while the hero shell is pending: date controls remain operable, the hero reserves its final visual footprint with accessible loading text, and secondary section skeletons/headings establish the page’s information hierarchy. Replace the current duplicate, isolated “Loading brief…” messages.
* On hero-shell completion, render the real hero and its provenance/navigation immediately, then request details independently. Populate each secondary panel as its result arrives; keep the hero and date control stable during detail loading or detail failure.
* On a date change, retain the selected date and shell, cancel/ignore stale hero/detail responses, clear only day-specific content, and never let an earlier hero overwrite the URL coordinate. Keep the detail drawer closing behavior intact.
* Present errors at their owning layer: unavailable hero means no Brief for the requested date; detail failure leaves the hero visible with a retryable “rest of brief” state rather than replacing the whole page with an error.

### Commit 4 — verify perceived and measured performance

* Work in: `api/tests`, the web test/build setup, and the benchmark documentation from Commit 1.
* Add client tests for cold entry, direct dated URL, a date switch during in-flight work, hero-success/detail-failure, and the absence of “Load Window” text from Brief controls.
* Verify the network sequence is hero shell → details, with no previous/next full-detail requests solely to populate navigation.
* Re-run the uncached benchmark and query plans; document before/after hero time, time-to-usable-date-control, detail time, and the selected query improvement. Keep the split even if profiling finds no safe SQL change—the progressive shell is independently valuable.
* Run `pytest api/tests/test_analysis.py` and `tsc --noEmit -p web/tsconfig.app.json` (plus the project’s Brief UI test command if available).

Do NOT touch: Map/Matrix playback loading, the shared URL cursor contract outside Brief’s delivery-day projection, or the underlying Brief/grade calculations unless profiling demonstrates a behavior-preserving data-access change.

## Acceptance

* [x] On first paint, the Brief shows stable chrome and a vertically centered ERCOT STRESS / bolt / loading-indicator treatment; date controls remain hidden until the hero, lede, and map have rendered, and no control or label says “Load Window.”
* [x] The hero and prior/next available-date state render from a fast shell response before secondary sections finish; date carets no longer depend on full Brief neighbor prefetches.
* [x] The delivery-date control is right-aligned with centered text between its carets; hovering or focusing the date explains that it is the ERCOT market delivery date, rather than today or the DAM auction date.
* [x] Hero prose/map, stat cards, and standouts begin concurrently; the global loader hides all of them until the hero is ready. Stat cards enter as one group with a reduced-motion-safe fade, rather than shifting in piecemeal.
* [x] Each lower panel has its own compact loading indicator, while the deferred detail request no longer duplicates the concurrently loaded standouts request.
* [x] A secondary-detail failure or slow response does not hide a successfully loaded hero or block choosing another date.
* [x] Direct URL dates, cold entry defaults, stale-response protection, unavailable days, and settled-cache rules work as before where applicable.
* [x] Query timings and `EXPLAIN` evidence identify the limiting uncached-detail path; dev’s absent `forecast_nodal` history takes the intentional artifact fallback, so no speculative query/index change was made.
* [ ] Full API and web verification pass (blocked by three pre-existing API test failures and existing repository-wide ESLint violations; focused Brief API tests and TypeScript pass).
