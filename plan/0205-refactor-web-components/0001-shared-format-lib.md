# 205-0001 - shared format lib

Type: refactor
Branch: refactor/205-0001-shared-format-lib

## Goal

* Promote `web/src/components/brief/briefFormat.tsx` to `web/src/lib/format.tsx` as the one shared formatting module.
* Fold the scattered money / number-with-dash / percent helpers into it and delete the local copies.
* Change no rendered output — every call site produces the same string as before.

## Context

* No shared format module exists today; `briefFormat.tsx` is already the de-facto one (imported by brief and matrix components) but mis-scoped under `components/brief/`.
* Money formatting is reimplemented 8 times; number-with-`—` and percent helpers are duplicated across map, panel, brief, and matrix files.
* This is the foundation branch — 0002 and 0003 consume the shared helpers.

## Approach

* Work in: `web/src/lib/format.tsx` (moved from `components/brief/briefFormat.tsx`); update all importers.
* Entry point: the existing `usd`, `percent`, `constraintName`, `zoneLabel`, `rankMovement`, `HistoryWhisker`, `HistoryBars` exports.
* Consolidate money formatters, keeping each distinct output variant as a named export (not one merged function): `usd`, `fmtDollars` (DetailCard:102), `fmtMag` (ConstraintReach:149), `fmtDailyStat` (ConstraintPanel:42), `compactMoney` (BriefDetailPanel:102), `formatDollar`/`formatExactDollar` (Legend:125/130), `marketValue` (MatrixReadDetail:344). Merge only ones whose logic is byte-identical.
* Consolidate number-with-`—`: `fmt`/`fmtSf`/`fmtCong` (DetailCard), `fmtNum`/`fmtScore` (SidePanel:61/72), `score`/`multiple` (BriefPage:861/863).
* Replace `pct` (BriefPage:1345) with `percent`; move utility helpers `numeric`, `gw`, `beats` (BriefPage) into the lib.
* `fmtDay` differs by timezone — `BriefPage:36` is `America/Chicago`, `ScoreboardPage:60` is `UTC`. Do NOT merge them into one default; if unified, require the zone as an explicit parameter.
* Comments: as helpers move, revise their comments to brief, plain-English intent — cut statistical jargon, over-explanation, and verbosity (power terminology is fine).
* Do NOT touch: `HistoryWhisker`/`HistoryBars` CSS ownership (that stays with the Brief stylesheet, handled in 0002), or `SignedBars` (intentionally separate from `HistoryBars`).

## Acceptance

* [x] `lib/format.ts` holds the shared helpers; `components/brief/briefFormat.tsx` is gone and all imports updated. (Landed as pure `.ts`, not `.tsx` — see note.)
* [x] No duplicate money/number/percent formatter definitions remain in `DetailCard`, `SidePanel`, `Legend`, `ConstraintReach`, `ConstraintPanel`, `MatrixReadDetail`, `BriefDetailPanel`, `BriefPage`.
* [x] The two `fmtDay` timezone behaviors are preserved. (Left in place, untouched — they differ in format too, not just zone.)
* [x] Comments on moved helpers are brief plain English — no statistical jargon, over-explanation, or verbosity.
* [x] `npx tsc -b` and `npm run lint` clean against baseline; affected surfaces render identically. (Verified in the docker dev container; local Node 18 can't build. Lint 33→27 problems, none new.)

### Deviation — glyphs out of the format module

`HistoryWhisker`/`HistoryBars` did **not** stay in the shared module. They are Brief-only (used just by `BriefPage` and `BriefDetailPanel`), so keeping them alongside the helpers forced `format.tsx` to export components — which trips `react-refresh/only-export-components` and grows lint on every helper added. They moved to `components/brief/HistoryGlyphs.tsx`, letting `lib/format.ts` be pure TS with no eslint-disable. Their CSS ownership is unchanged (still BriefPage's page-level `<style>`, per 0002).

Grouped into commits: (1) promote briefFormat → `lib/format`; (2) money formatters; (3) number formatters; (4) percent/utility helpers; (5) labelled sections; (6) glyphs → brief component.
