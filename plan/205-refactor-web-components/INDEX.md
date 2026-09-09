# 205 - Web refactor — survey & index

Type: survey (planning only)
Scope: `web/src/` mechanical refactors — component extraction from large files, dedup of scattered helpers into a shared lib, reusable UI-effect hooks. No behavior changes.

## Sub-plans

| plan | branch of work | tiers |
|------|----------------|-------|
| `0001-shared-format-lib.md` | dedup helpers → one `lib/format` | Tier 2 |
| `0002-briefpage-components.md` | `BriefPage` → reusable brief components | Tier 1 |
| `0003-large-file-components.md` | other large files → subcomponents | Tier 1 |
| `0004-map-workspace-seams.md` | `MapWorkspace` → hooks + panes | (own survey) |
| `0005-ui-effect-hooks.md` | reusable dismiss hooks + `hooks/`→`features/` placement | — |
| `0006-api-types-split.md` | `api/types.ts` → per-domain files behind a barrel | Tier 1 |
| `0007-detail-renderer-consolidation.md` | unify the shared constraint/node detail KV row (full body merge deferred) | Tier 4 |

Tier 3 (shared KV primitive) and Tier 4 (renderer merge, `GridMap`) are **not** sub-plans — blocked on a design decision or needing behavioral coverage first. They stay parked below as non-goals. The tiers below are the full map; the sub-plans are the phase-1 slices carved from Tiers 1–2 plus hooks.

## Size baseline (top files)

| lines | file |
|------:|------|
| 1869 | `pages/BriefPage.tsx` |
| 1327 | `components/map/GridMap.tsx` |
| 1072 | `workspaces/MapWorkspace.tsx` *(0004)* |
|  996 | `api/types.ts` |
|  826 | `components/map/DetailCard.tsx` |
|  775 | `components/brief/BriefDetailPanel.tsx` |
|  763 | `pages/ScoreboardPage.tsx` |
|  689 | `components/matrix/MatrixReadDetail.tsx` |
|  681 | `components/panels/SidePanel.tsx` |
|  583 | `components/map/Legend.tsx` |
|  482 | `lib/colors.ts` |

---

## Tier 1 — Big single-file → organized subcomponents

### 1. `pages/BriefPage.tsx` (1869 → ~250 target) — headline win

The file is already internally sectioned into self-contained, single-entry components. Almost all of it is mechanically liftable into `components/brief/`:

| lines | unit | destination |
|------:|------|-------------|
| 56–368  | `StandoutsPanel` | `components/brief/StandoutsPanel.tsx` |
| 370–530 | `TopConstraintsPanel` | `components/brief/TopConstraintsPanel.tsx` |
| 532–711 | `TopNodesPanel` | `components/brief/TopNodesPanel.tsx` |
| 713–830 | `ContextPanel` | `components/brief/ContextPanel.tsx` |
| 861–1333 | Forecast Grade cluster: `ScoreWhisker`, `GradeCard`, `GradeHalf`, `ForecastGrade` + `score`/`multiple`/`beats`/`gradeMetric`/`gradeSource`/`gradeSourceLabel` + `BRIEF_*_SOURCE` consts | `components/brief/ForecastGrade.tsx` (~470 lines, one export) |
| 47–54, 832–859 | `LoadingState`, `DualStatBox` primitives | `components/brief/` (or shared, see Tier 3) |

After extraction the default export (1361–1869) is pure composition + data wiring from `useBriefDay`.

**Trap — the `<style>` block (1650–1866, ~216 lines).** Not a clean move. `briefFormat.tsx`'s `HistoryWhisker`/`HistoryBars` glyphs and `BriefDetailPanel` both depend on classes defined *only* here (`.an-history-whisker`, `.an-history-bars`, `.an-table*`, `.an-grade-card*`) by being mounted under this page. Extract to a **shared stylesheet** the brief surfaces both import — do not just relocate it into one component's scope. Recommend doing the style split as its own commit, after the component splits, so a regression is bisectable.

Suggested commit order: (a) Forecast Grade → own file; (b) the four panels → own files; (c) primitives + local formatters → shared lib (Tier 2); (d) `<style>` → shared stylesheet.

### 2. `components/map/DetailCard.tsx` (826)

Already has clean seams: `SpBody` (111), `ExposuresBody` (205), `ReachBody` (360), plus chips `TypeChip`/`NodeChip`/`SfSign` and `Row`. Each *Body* is a self-contained render tree → `components/map/detail/`. Local formatters `fmt`/`fmtSf`/`fmtDollars`/`fmtCong` (64–110) go to the shared lib (Tier 2).

### 3. `components/brief/BriefDetailPanel.tsx` (775)

`HistoryBlock` (114), `SignedBars` (221), `ConstraintEvidence` (301), `NodeEvidence` (414) are extractable. `Fact` (68) and `compactMoney` (102) → shared (Tier 2/3).

### 4. `pages/ScoreboardPage.tsx` (763)

`SeriesChart` (70), `LiveGradePanel` (384), `SplitTable` (457), `Glossary`/`Term` (530/547) are independent → `features/scoreboard/`. `fmtWeek`/`fmtDay` (53/60) → shared, **but see the fmtDay trap below**.

### 5. `components/matrix/MatrixReadDetail.tsx` (689)

`ConstraintRead` (167), `NodeRead` (348), `DriverRow` (316), `MemberLobe`/`MemberRow` (124/106), `DetailSummary` (80) → `components/matrix/read/`.

### 6. `api/types.ts` (996) → `0006`

Pure type declarations, already sectioned by endpoint. Splitting by domain (matrix/map/scoreboard/brief/analysis) behind a barrel `index.ts` keeps every `../api/types` import unchanged, so it's safe but low-lift. Carved into `0006-api-types-split.md`.

---

## Tier 2 — Duplicate helpers → one shared `lib/format.ts`

There is **no** shared format module today. `briefFormat.tsx` is already the de-facto one (imported by brief *and* matrix components) but is mis-scoped under `components/brief/`. Recommend promoting it to `lib/format.ts` (or `lib/format.tsx` for the glyph components) and consolidating the scattered copies.

**Money formatters** — 8 near-duplicate implementations:
`usd` (briefFormat), `fmtDollars` (DetailCard:102), `fmtMag` (ConstraintReach:149), `fmtDailyStat` (ConstraintPanel:42), `compactMoney` (BriefDetailPanel:102), `formatDollar`+`formatExactDollar` (Legend:125/130), `marketValue` (MatrixReadDetail:344).

**Number-with-`—`-fallback formatters** — repeated toFixed/dash pattern (19 files touch `toFixed`/`toLocaleString`):
`fmt`/`fmtSf`/`fmtCong` (DetailCard), `fmtNum`/`fmtScore` (SidePanel:61/72), `score`/`multiple` (BriefPage:861/863).

**Straight dedupe:** `pct` (BriefPage:1345) is `percent` (briefFormat:13) minus the null guard — replace with `percent`.

**Utility:** `numeric` (BriefPage:1335), `gw` (BriefPage:1340), `beats` (BriefPage:865).

> **Trap — `fmtDay` is NOT one function.** `BriefPage.tsx:36` formats in `America/Chicago`; `ScoreboardPage.tsx:60` formats in `UTC`. They look identical and differ only in `timeZone`. Merging them naively is a correctness bug. If unified, it must take the zone as a parameter with no default.

Consolidate incrementally (one formatter family per commit) so each diff is reviewable and any rendering change is caught in isolation.

---

## Tier 3 — Shared component primitives (moderate risk: CSS coupling)

- **KV / stat row.** `Fact` is structurally identical in `BriefDetailPanel` (`bdp-kv__*`) and `MatrixReadDetail` (`mrd-kv__*`); `SidePanel`'s `Stat` and `BriefPage`'s `DualStatBox` are the same label/value idiom. Candidate for one `<Fact>`/`<KeyValue>` primitive. Blocked on the per-surface CSS namespaces — needs a class-name prop or a unified token, so it's a design decision, not a pure move.
- **`SignedBars` vs `HistoryBars`.** Intentionally two sizes (per the `briefFormat.tsx` comment: panel gets full-width, table gets tiny inline). Leave as-is, or unify behind a `size` prop only if it stays a one-liner.

---

## Tier 4 — Deferred (needs coverage first; out of phase 1)

- **Parallel constraint/node detail renderers → `0007`.** `BriefDetailPanel`'s `ConstraintEvidence`/`NodeEvidence` and `MatrixReadDetail`'s `ConstraintRead`/`NodeRead` looked like two surfaces solving the same problem. On inspection they share little beyond the KV row — divergent data shapes, layouts, and sections — so `0007` unified only the shared `Fact` KV primitive (one `.kv__*` namespace) and left the bodies separate. The full body merge and its test net are deferred, not done; see `0007-detail-renderer-consolidation.md`.
- **`GridMap.tsx` (1327).** Mostly MapLibre expression builders + imperative layer wiring; cohesive and stateful. Not a mechanical extraction target for phase 1.

---

## Recommended phase-1 sequencing

1. `0001` — foundation; `0002`/`0003`/`0005` consume the shared helpers.
2. `0002`, `0003`, `0004`, `0005` — independent after `0001`, any order.
3. Tier 3 KV primitive only after the CSS-namespace decision is made (not a sub-plan yet).

Each sub-plan: `npx tsc -b` + `npm run lint` clean against baseline, and a visual smoke of the affected surface (extractions are move-only, so a diff that changes rendered output is a mistake).
