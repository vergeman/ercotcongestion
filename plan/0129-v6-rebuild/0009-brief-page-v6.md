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
  are out of scope for v6. Land panel by panel
  behind each backend step rather than as one cutover.
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
  cursor, so the URL is shareable from first paint.
* Re-point the catch-all deliberately — decide what unknown paths do rather than letting
  the brief inherit `*`.
* Do NOT touch: Map, Matrix, Scoreboard, `useExplorerSession`, or `0128`'s refactor in
  reverse.

## Acceptance

* [ ] `/` renders the brief; Map and Matrix are unchanged in behaviour and appearance.
* [ ] The scrubber still works on `/map` and `/matrix` — Load Window, play, step, sparkline — with no regression.
* [ ] No file under `web/src/components/playback/` is deleted, and `useExplorerSession.ts` is unmodified.
* [ ] The brief page renders no transport control, and its URL still carries a valid `?t/?ws/?we`.
* [ ] Navigating brief → `/map` lands on the same day with no translation step.
* [ ] Unknown paths resolve to a deliberate destination, stated in the PR.
* [ ] `tsc --noEmit -p web/tsconfig.app.json` clean.
