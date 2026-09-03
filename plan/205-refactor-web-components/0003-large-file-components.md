# 205-0003 - large files to organizational components

Type: refactor
Branch: refactor/205-0003-large-file-components

## Goal

* Split four large components into their already-cohesive subcomponents, move-only.
* Land each file independently so any single extraction can ship or revert on its own.

## Context

* `DetailCard`, `BriefDetailPanel`, `ScoreboardPage`, and `MatrixReadDetail` each hold 3–4 self-contained render trees in one file.
* Depends on 205-0001 for the shared formatters these files currently define locally.
* These are independent of each other and of 0002 — any order.

## Approach

* Each target: extract the listed subcomponents to a co-located folder, keep props/markup/classnames unchanged, leave the parent as composition.
  - `components/map/DetailCard.tsx` (826) → `components/map/detail/`: `SpBody` (111), `ExposuresBody` (205), `ReachBody` (360), chips `TypeChip`/`NodeChip`/`SfSign`, `Row`.
  - `components/brief/BriefDetailPanel.tsx` (775): `HistoryBlock` (114), `SignedBars` (221), `ConstraintEvidence` (301), `NodeEvidence` (414).
  - `pages/ScoreboardPage.tsx` (763) → `features/scoreboard/`: `SeriesChart` (70), `LiveGradePanel` (384), `SplitTable` (457), `Glossary`/`Term` (530/547).
  - `components/matrix/MatrixReadDetail.tsx` (689) → `components/matrix/read/`: `ConstraintRead` (167), `NodeRead` (348), `DriverRow` (316), `MemberLobe`/`MemberRow` (124/106), `DetailSummary` (80).
* Do NOT touch: the parallel constraint/node renderers as a *shared* component (BriefDetailPanel vs MatrixReadDetail) — that is a behavioral merge, deferred until it has focused coverage.
* Comments: as subcomponents move, revise their comments to brief, plain-English intent — cut statistical jargon, over-explanation, and verbosity (power terminology is fine).
* Do NOT touch: `GridMap.tsx` (stateful MapLibre wiring, not a mechanical target) or `api/types.ts`.

## Acceptance

* [ ] Each of the four parent files is reduced to composition of its extracted subcomponents.
* [ ] No local formatter definitions remain (they resolve to `lib/format` from 0001).
* [ ] Every extraction is move-only — no prop, markup, or classname changes.
* [ ] Comments on moved subcomponents are brief plain English — no statistical jargon, over-explanation, or verbosity.
* [ ] `npx tsc -b` and `npm run lint` clean against baseline; each affected surface renders identically.
