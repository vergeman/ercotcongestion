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

* [ ] `lib/format.tsx` holds the shared helpers; `components/brief/briefFormat.tsx` is gone and all imports updated.
* [ ] No duplicate money/number/percent formatter definitions remain in `DetailCard`, `SidePanel`, `Legend`, `ConstraintReach`, `ConstraintPanel`, `MatrixReadDetail`, `BriefDetailPanel`, `BriefPage`.
* [ ] The two `fmtDay` timezone behaviors are preserved.
* [ ] Comments on moved helpers are brief plain English — no statistical jargon, over-explanation, or verbosity.
* [ ] `npx tsc -b` and `npm run lint` clean against baseline; affected surfaces render identically.
