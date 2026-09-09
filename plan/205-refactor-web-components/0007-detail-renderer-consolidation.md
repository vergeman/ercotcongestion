# 205-0007 - Unify the constraint/node detail renderers

Type: refactor (behavioral — needs coverage first)
Branch: refactor/205-0007-detail-renderer-consolidation

## Goal

* Collapse the two parallel constraint/node detail renderers into one shared body component both surfaces call.
* Do it behind a safety net: land test coverage of both surfaces FIRST, then consolidate under it.

This is the Tier 4 deferral in the INDEX. Unlike 0002/0003/0006 it is not a move-only diff — it changes rendered output on two surfaces — so it is explicitly sequenced coverage-first.

## The duplication

Two files render the same concept — a constraint or node, its numbers, drivers, members, and 30-day history — with independent implementations:

| | `brief/detail/BriefDetailPanel.tsx` (775) | `matrix/MatrixReadDetail.tsx` (689) |
|---|---|---|
| opened from | a Brief evidence-table row | the Matrix grid read view |
| constraint body | `ConstraintEvidence` | `ConstraintRead` |
| node body | `NodeEvidence` | `NodeRead` |
| KV row primitive | `Fact` → `.bdp-kv__*` | `Fact` → `.mrd-kv__*` |
| history glyph | hand-rolled `.bdp-whisker` markup | shares `HistoryGlyphs` / reach parts |
| chrome | portal drawer + focus trap | inline pane |
| local interaction | — | node-table sort state in the shell |

Tells: two structurally identical `Fact` components differing only in CSS namespace; BriefDetailPanel re-implements a whisker that already exists in `HistoryGlyphs`.

## The three real blockers (why it isn't mechanical)

1. **Divergent data shapes.** BriefDetailPanel takes a `BriefSelection` (brief row + hero cursor); MatrixReadDetail takes `constraintRow`/`nodeMeta`/frame + reach data. The shared body needs a normalized view-model both call sites adapt into — designing that model is the core of the work.
2. **Two CSS namespaces** (`bdp-` vs `mrd-`). The shared body needs one namespace (or a class-name/token prop). Same blocker as the Tier-3 KV primitive.
3. **Shell vs body split.** The outer chrome differs (drawer+focus-trap vs inline pane with node sort). Only the inner body consolidates; each shell keeps its own chrome and passes the body its view-model plus interaction hooks (e.g. node sort stays owned by the matrix shell).

## Approach

### Phase A — coverage (own commit, no behavior change)

* Stand up a test runner. The project is Vite → **vitest + @testing-library/react + jsdom**; there is no test setup today, so this phase adds it (`vitest.config`, a `test` script, one setup file).
* Add render tests that snapshot both surfaces against fixture data, for constraint AND node, in both `settled` and unsettled states: the Brief detail drawer and the Matrix read pane. Capture the KV facts, drivers, member/reach lists, and the history block.
* Keep fixtures small and colocated (`__fixtures__/`); these snapshots are the regression oracle for Phase B.

### Phase B — consolidate (separate commit(s), under Phase A's net)

* Define the shared view-model and a `components/brief/detail/`- or a new `components/detail/`-level `ConstraintDetail`/`NodeDetail` body (placement decided when the view-model is drafted — if both surfaces import it, it should not live under `brief/`).
* Pick one CSS namespace/token for the body; drop the duplicate `Fact` and the hand-rolled whisker in favor of the shared primitive + `HistoryGlyphs`.
* Rewrite each shell to adapt its data into the view-model and mount the shared body. Delete `ConstraintEvidence`/`NodeEvidence` and `ConstraintRead`/`NodeRead` once unused.
* Re-run Phase A snapshots. Intentional visual changes (namespace unification) get the snapshot updated in the same commit with the diff called out in the message; anything unexpected is a regression to fix, not to bless.

## Acceptance

* [ ] Phase A merged first: a working test runner + passing snapshots of both detail surfaces (constraint & node, settled & unsettled).
* [ ] One shared constraint/node body renders both surfaces; the four old body components are deleted.
* [ ] One KV primitive and `HistoryGlyphs` used on both; no `bdp-`/`mrd-` duplicate of either remains.
* [ ] Each shell keeps its own chrome (drawer/focus-trap; inline/node-sort) — only the body is shared.
* [ ] `npx tsc -b`, `npm run lint`, `vitest`, and `vite build` all clean.
* [ ] Any snapshot change is intentional and explained; no unreviewed rendered-output drift.
