# 205-0006 - api/types split by domain

Type: refactor
Branch: refactor/205-0006-api-types-split

## Goal

* Split `web/src/api/types.ts` (1000 lines) into per-domain files under `api/types/`.
* Keep the `../api/types` import path working for all 39 importers via a barrel `index.ts`.
* No type changes, no renames — a pure file move behind an unchanged public path.

## Context

* The file is already sectioned by endpoint with banner comments; the seams are clean.
* 39 files import from `"../api/types"` today. A barrel that re-exports every domain file keeps every one of those imports byte-for-byte unchanged, so the split touches no consumer.
* Listed as Tier 1 #6 in the INDEX ("optional, low value") and on the do-NOT-touch list in 0003. Promoted to its own sub-plan so it isn't done piecemeal inside another task.

## Domain seams (current line spans)

| lines | domain | destination |
|------:|--------|-------------|
| 1–125   | `/matrix/frame`, `/ercot_range` | `api/types/matrix.ts` |
| 126–438 | `/forecast_range`, `/conditions_range`, `/map/*` SF, `/map/constraints/ranked` | `api/types/map.ts` |
| 439–620 | `/scoreboard/summary` weekly + daily live grade | `api/types/scoreboard.ts` |
| 621–894 | brief hero, top constraints/nodes, standouts, context, analysis grade | `api/types/brief.ts` |
| 895–1000 | `/analysis/node`, `/analysis/settlement-points` attribution | `api/types/analysis.ts` |

Exact boundaries are the banner comments, not the line numbers above — cut on the banners.

## Approach

* Create `api/types/` and move each domain block into its own file, preserving the banner comments.
* Cross-domain references (e.g. a brief type that reuses a shared/map type) import across the new files. Watch for a genuinely shared primitive used by several domains — if one exists, put it in `api/types/common.ts` rather than duplicating or forcing a domain to own it.
* Add `api/types/index.ts` that `export *` from each domain file. Delete the old `api/types.ts`.
* Do NOT rename any type or change any field. The diff should be moves plus the barrel.
* Prefer `git mv`-style history where practical, but a split file can't be a single rename — keep each block's text identical so the move is reviewable.

## Acceptance

* [ ] `api/types.ts` is gone; `api/types/` holds the domain files plus `index.ts`.
* [ ] Every existing `from "../api/types"` import still resolves and is unchanged.
* [ ] No type declaration renamed or altered; blocks moved verbatim.
* [ ] `npx tsc -b` and `npm run lint` clean against baseline; `vite build` succeeds.
