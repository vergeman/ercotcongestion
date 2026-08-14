# 0129-0009 - brief-page-v6

Type: feat
Branch: feat/0129-0009-brief-page-v6
Depends on: `0002`; further panels land behind `0003`/`0005`/`0006`/`0007` as they arrive

## Goal

* Build `web/src/pages/BriefPage.tsx` as the v6 layout and route `/` to it.
  Keep `AnalysisPage.tsx` and `/analysis` intact until `0012` removes the
  legacy precomputed-brief reader.
* Un-mount the playback scrubber from this page while leaving Map and Matrix untouched.
* Keep the page reading and writing the shared URL time coordinate.

## Context

* v6 is the entry point, not a fourth view. The Map becomes something the brief links
  *into* (`0011`).
* `AnalysisPage.tsx` is the 1,567-line legacy blob reader. Leave it untouched;
  `BriefPage.tsx` replaces it at the product entry point while the legacy route
  remains available through `0012`. Keep Brief styles inline under the `an-*`
  prefix.
* `web/src/main.tsx` currently sends both `/` and every unknown path to `<App />` (the
  Map) via `path="*"`. Both behaviours are in one route and have to be separated.
* `0128` shipped one shared scrubber to Map, Matrix and Analysis via `ExplorerLayout` +
  `ExplorerScrubber`. The Brief deliberately does not mount that transport. An hour cursor is
  the wrong control for a page whose unit is a delivery day.
* Ships with `0010`. Un-mounting the scrubber removes the page's only way to change day,
  so `0009` alone strands the reader on whatever day the URL carried.

## Approach

* Work in: `web/src/pages/`, `web/src/main.tsx`
* Build the v6 sections in the order the backend lands them — Standouts, Top
  Constraints, Top Nodal Congestion, Forecast Grade, Context. Source–sink pairs
  are out of scope for v6. Land panel by panel behind each backend step rather
  than as one cutover.
  * Top Constraints reads `/analysis/top-constraints`: the server ranks the full
    forecast-artifact μ vocabulary and returns same-key DAM evidence. Keep
    `/analysis/forecast-mu` key-scoped for follow-up reads; the Brief must not
    re-rank an old truncated `analysis_brief` cast in the browser.
* **Scrubber — un-integrate, delete nothing:**
  * `/map` and `/matrix` keep the scrubber exactly as today — same `ExplorerScrubber`,
    Load Window, play/step/sparkline, same shared session. **If a diff here deletes a
    component under `web/src/components/playback/` or changes
    `web/src/hooks/useExplorerSession.ts`, it is wrong.**
* On the Brief only: do not render `ExplorerScrubber`, do not add the whole-day
  `rightSlot` toggle, and keep it outside `ExplorerLayout`; it reads and writes
  the shared URL coordinate directly.
  * Leave untouched: `web/src/hooks/useTimeCursor.ts`, `snapToFrames`, the
    `?t/?span/?run/?ws/?we` contract, and the coordinate carry in
    `web/src/components/layout/HeaderNav.tsx:37` and `web/src/App.tsx:25`.
* **The coordinate stays, the transport goes.** Day shown = the America/Chicago day of
  `?t` — a single instant maps to exactly one delivery day, unlike `?ws`/`?we`, which on
  the Map can span a week. Same day-cut as everywhere else: UTC instant, cut in
  America/Chicago, HE = local hour + 1.
* `?date` is **not** carried over to the Brief. The legacy page read it (`AnalysisPage.tsx:1017`) *and*
  derived a day from the cursor — two inputs for one piece of state. It dies with the
  page; the cursor is the only source.
* Cold entry to `/` with no `?t`: default to the latest date with a brief and write the
  cursor, so the URL is shareable from first paint. This must have a v6 discovery
  endpoint before `0012` removes `/analysis/brief/latest`; the Brief cannot retain a
  hidden dependency on the legacy blob reader.
* Re-point the catch-all deliberately — decide what unknown paths do rather than letting
  the brief inherit `*`.
* Do NOT touch: Map, Matrix, Scoreboard, `useExplorerSession`, or `0128`'s refactor in
  reverse.

## Rendering modes

* The page has two explicit response-driven modes. Select the mode from the
  availability of settled evidence in the served response, never from the browser clock
  or a guessed DAM publication time:
  * **Forecast-only** — the lean morning brief. Show the forecast hero, forecast
    standings and forecast-versus-forecast-history context. Do not render empty DAM
    columns, rank movement, outcome claims, or a faux accuracy grade. Grade instead
    states that settlement is pending and, where useful, shows only its forecast-side
    inputs. Details and Standouts make forecast claims only.
  * **Post-settle** — the validation brief. Render the DAM-settled columns, deltas,
    rank movement, realized coverage, settled Standouts, and the Forecast Grade.
* The two modes keep the same page order, selected-day coordinate, and row identity.
  A forecast-only render is intentionally slimmer, not a second layout with a divergent
  interaction model.

## Panel contracts and interactions

* **Standouts** is a real ranked, actionable panel, not a stage placeholder. Its
  response must identify the element, whether the claim is forecast-only or settled,
  today's forecast value, its own trailing forecast baseline, and (post-settle only)
  same-key DAM evidence. It must include chronic/near-floor items that the old cast
  omitted when they materially differ from their own history. `0004` and `0005` provide
  the history and full-artifact vocabulary this needs.
* **Top Constraints** uses the full forecast-artifact vocabulary, with same-key DAM
  evidence when available. The history column is a real trailing-30-day visual/value,
  not a placeholder dash. The table must preserve the prototype's compact grouped
  Forecast / DAM SETTLED / history presentation in post-settle mode and collapse to
  Forecast / history in forecast-only mode. In forecast-only mode it is the forecast
  top-*k*. Post-settle it is the ordered union **DAM top-*k* followed by forecast
  top-*k* entries not already in DAM top-*k***. Retain both ranks: the appended rows
  make forecast calls that fell out of the actual leaders visible, while DAM-only rows
  expose misses. The joined result may therefore contain more than *k* rows.
* **Top Nodal Congestion** presents top 15 *unique locations* over the market-peak
  `7×16` value window. Its grouping must be stable and documented for the delivery-day
  display: use delivery-day ESSP study membership in both modes to collapse equivalent
  settlement points; retain an explicit fallback for points absent from that ESSP vintage.
  Do not silently base a daily table on one arbitrary hourly membership snapshot.
  It needs its own real trailing-history display, dominant-driver attribution, zone,
  share, coverage, and forecast/settled rank movement. Its phase ranking follows the
  same rule as constraints: forecast top 15 before settlement; DAM top 15 first after
  settlement, then forecast top-15 entries absent from that DAM set.
* **Forecast Grade** is post-settle only. Its cards retain the served calculation and
  small formula popover, and add real trailing grade/history whiskers rather than a
  decorative scale. The forecast-only replacement is a compact settlement-pending
  status, not zeroes or null-valued grade cards.
* **Context** is a real, server-authored closing panel. It excludes the prototype's
  weather/load Conditions block, which is moving elsewhere. It contains **Congestion by
  voltage class** (how daily μ distributes across voltage classes) and **Chronic
  Elements** (constraints bound on at least 24 of the trailing 30 delivery days). It
  must not become frontend-owned narrative.
* Every Standout and every selectable row in Top Constraints and Top Nodal Congestion
  exposes the stable element identity and coordinates needed by the shared detail-panel
  contract. The interactive panel itself is deliberately sequenced as `0013`, after
  this page's data and `0011`'s element-aware Map handoff are available.

## Delivery state at plan revision

* The root route, Brief shell, date control, server-authored hero, compact Top
  Constraints and Top Nodal tables, and post-settle Grade cards are present.
* Standouts is now server-backed and anomaly-selected, with forecast and DAM-only
  appended rows, full grouped table columns, and real 30-day history visuals. Top
  Constraints and Top Nodal history columns are likewise served from DAM history. Context
  now serves voltage-class distribution and chronic elements; Conditions remains deferred
  outside the Brief. Grade history is materialized per settled delivery day and served as
  a real trailing track. The row detail panel and
  element-aware Map handoff are deliberately owned by
  `0013` and its `0011` dependency, rather than by this page plan.

## Acceptance

* [x] `/` renders the brief; Map and Matrix are unchanged in behaviour and appearance.
* [x] The scrubber still works on `/map` and `/matrix` — Load Window, play, step, sparkline — with no regression.
* [x] No file under `web/src/components/playback/` is deleted, and `useExplorerSession.ts` is unmodified.
* [x] The brief page renders no transport control, and its URL still carries a valid `?t/?ws/?we`.
* [x] Navigating brief → `/map` lands on the same day with no translation step.
* [x] Unknown paths deliberately redirect to `/`.
* [x] Cold entry discovers a v6 available day without calling `/analysis/brief/latest`.
* [x] The response selects one of the two documented rendering modes. Forecast-only is
      visibly slimmer and makes no settled/outcome/grade claim; post-settle renders
      same-key DAM evidence and the full grade.
* [x] Standouts is server-backed, anomaly-selected, and carries forecast/DAM evidence
      plus real 30-day history visuals.
* [x] Top Constraints and Top Nodal have real trailing 30-day history, not placeholder cells.
* [x] Top Nodal shows 15 unique 7×16 locations using the documented pre-/post-settle
      grouping rules and an explicit missing-ESSP fallback.
* [x] Forecast-only tables are forecast top-*k*. Post-settle tables are DAM top-*k*
      followed by forecast top-*k* entries absent from DAM top-*k*, ordered with DAM
      leaders first and retaining both ranks; the joined table may exceed *k* rows.
* [x] The shared accessible detail panel is explicitly deferred to `0013` (after `0011`'s
      typed Map handoff); it is not a completion condition for this page-only plan.
* [x] Context is server-authored and contains daily congestion by voltage class plus
      trailing-30-day chronic elements; the weather/load Conditions block is excluded.
* [x] Grade whiskers are backed by trailing grade history; forecast-only shows a
      settlement-pending replacement rather than empty grade metrics.
* [x] `tsc --noEmit -p web/tsconfig.app.json` clean.
