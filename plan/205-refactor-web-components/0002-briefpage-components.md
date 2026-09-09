# 205-0002 - BriefPage to reusable components

Type: refactor
Branch: refactor/205-0002-briefpage-components

## Goal

* Reduce `web/src/pages/BriefPage.tsx` (1869 lines) to a composition + data-wiring component (~250 lines).
* Extract its self-contained panels and the Forecast Grade cluster into `components/brief/`.
* Move the page's shared `<style>` block into a stylesheet the Brief surfaces import.

## Context

* The file is already internally sectioned into single-entry components; most of it lifts mechanically.
* Depends on 205-0001 for the shared formatters the panels use.
* The `<style>` block (1650–1866) is not page-private: `HistoryWhisker`/`HistoryBars` and `BriefDetailPanel` rely on its classes by being mounted under the page.

## Approach

* Work in: `web/src/pages/BriefPage.tsx`; add files under `web/src/components/brief/`.
* Extract, one component per file, preserving props and markup exactly:
  - Forecast Grade → `ForecastGrade.tsx` (`ScoreWhisker`, `GradeCard`, `GradeHalf`, `ForecastGrade` + `score`/`multiple`/`beats`/`gradeMetric`/`gradeSource`/`gradeSourceLabel`/`BRIEF_*_SOURCE`; lines 861–1333).
  - `StandoutsPanel` (56–368), `TopConstraintsPanel` (370–530), `TopNodesPanel` (532–711), `ContextPanel` (713–830) → one file each.
  - `LoadingState` (47–54), `DualStatBox` (832–859) → small shared brief primitives.
* Do the `<style>` move as its own commit, last: relocate to a shared Brief stylesheet imported by `BriefPage` and `BriefDetailPanel`. Do not scope it into a single component.
* Keep the default export as the owner of `useBriefDay` wiring, cursor/selection state, and layout.
* Comments: as components move, revise their comments to brief, plain-English intent — cut statistical jargon, over-explanation, and verbosity (power terminology is fine).
* Do NOT touch: `useBriefDay`, `BriefHero`, `BriefEvidence`, `BriefDayControls`, `BriefDetailPanel` internals, or any rendered markup/classnames.

## Follow-on grouping (beyond the original extract)

After the extraction, the brief components were grouped by role and given barrels:

```
components/brief/
  HistoryGlyphs.tsx        shared by evidence + detail
  hero/     BriefHero, BriefDayControls, DualStatBox + index.ts
  evidence/ BriefEvidence, StandoutsPanel, TopConstraintsPanel, TopNodesPanel,
            ForecastGrade, ContextPanel, LoadingState + index.ts
  detail/   BriefDetailPanel + index.ts
```

`BriefPrimitives` was dissolved: `DualStatBox` → `hero/` (its only consumer), `LoadingState` → `evidence/` (its only consumers). Subdir `index.ts` barrels expose each group's public surface; `LoadingState` and `HistoryGlyphs` stay internal. `BriefPage` imports through the three barrels.

## Acceptance

* [x] `BriefPage.tsx` no longer defines the panels or the grade cluster inline; it composes them. (1869 → ~340 lines)
* [x] The `<style>` block lives in a shared stylesheet (`features/brief/brief.css`) imported by `BriefPage` and `BriefDetailPanel`; whisker/bars glyphs still render on both.
* [x] Each extracted component is move-only (no prop or markup changes).
* [x] Comments on moved components are brief plain English — no statistical jargon, over-explanation, or verbosity.
* [x] `npx tsc -b` and `npm run lint` clean against baseline (only pre-existing `exhaustive-deps` warnings); `vite build` succeeds.
* [ ] Visual smoke — Brief page renders identically at desktop and mobile widths. *(not verified here: the live container serves the master checkout, not this worktree.)*
