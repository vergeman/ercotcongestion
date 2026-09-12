# 205-0007 - Unify the constraint/node detail KV primitive

Type: refactor (behavioral — namespace unification only)
Branch: refactor/205-0007-detail-renderer-consolidation

## Goal

* Collapse the one genuinely-duplicated primitive — the constraint/node detail **KV row** — into a single shared component both surfaces call, under one CSS namespace.
* Leave the two detail **bodies** separate. They look parallel but are not: see the scope decision below.

## Scope decision (reduced from the original full-body merge)

The INDEX filed this as a Tier-4 "unify the two parallel constraint/node detail renderers", implying one shared body both shells adapt into. Reading the actual code, that merge was rejected — the two surfaces share far less than the duplication table suggests:

* `HistoryGlyphs` is **already** shared (0003); Brief's `HistoryBlock` uses the shared whisker. The "re-implements a whisker" tell is stale.
* The bodies are **deeply divergent**, not parallel: different data sources (Brief pre-aggregated `Top*`/`Standout*` rows vs Matrix live `useFullConstraintReach` / `getAnalysisNode` fetches), different facts, different layouts (Brief single-column + history + why; Matrix two-column summary + driver table + right-rail map), different reach presentation (flat `MemberList` vs import/export `MemberLobe`s). Matrix renders **no** history; Brief renders **no** drivers.

Forcing those into one body means a `variant`-branched component that is really two implementations under one roof — a worse read than what's there. So the only honest, low-risk consolidation is the shared KV row.

**A test runner was NOT added.** The original plan sequenced a vitest safety net first; a prototype was built and then removed by request (refactoring is mid-flight; snapshots weren't worth maintaining yet). The KV change is a pure class-rename verified by `tsc` + `lint` + `vite build` and a diff review instead. See the test-runner setup notes for how to re-add vitest when tests return.

## The duplication that was removed

Two structurally identical `Fact` components differing only in CSS namespace:

| | `brief/detail/Fact.tsx` | `matrix/read/Fact.tsx` |
|---|---|---|
| row/label/value classes | `.bdp-kv__*` | `.mrd-kv__*` |
| tone prop | `"positive"` / `"negative"` | `"pos"` / `"neg"` |
| numeric right-align | — | `numeric` prop |

Both re-declared the same value tone (`--pos` danger, `--neg` accent) and, for Matrix, numeric alignment.

## What shipped

* New shared `components/detail/Fact.tsx` (props `label`, `value`, `tone?: "pos" | "neg"`, `numeric?`) emitting one `.kv__*` namespace, plus `components/detail/detail.css` holding the shared base row + value tone + numeric rules.
* Both `Fact.tsx` copies deleted; all four bodies (`ConstraintEvidence`, `NodeEvidence`, `ConstraintRead`, `NodeRead`) import the shared one. `NodeEvidence`'s `dollarTone` moved to `"pos"/"neg"`; `DriverTable`'s `mrd-kv__value--pos/neg` → `kv__value--pos/neg`.
* The `.bdp-kv` / `.mrd-kv` **containers stay** and keep their own layout (drawer flex vs two-column grid), now expressed as container-scoped overrides of the shared `.kv__*` rules — specificity relationships (Matrix summary/media overrides) preserved.

## Acceptance

* [x] One shared KV row primitive (`components/detail/Fact`) renders both surfaces; both `bdp-`/`mrd-` `Fact.tsx` copies are deleted.
* [x] One `.kv__*` namespace for the row/label/value; no `bdp-kv__*` / `mrd-kv__*` element classes remain (the `.bdp-kv` / `.mrd-kv` layout containers intentionally stay).
* [x] `HistoryGlyphs` already shared by both (0003) — left as-is.
* [x] Each shell keeps its own chrome and body; only the KV row is shared.
* [x] `npx tsc -b`, `npm run lint` (touched files), and `vite build` clean.
* [ ] **Deferred, not done:** the full body merge (one `ConstraintDetail`/`NodeDetail` view-model both shells adapt into, deleting the four body components). Rejected for now — see scope decision. Revisit only with a test net and a real appetite for centralizing divergent logic.
* [ ] **Deferred:** a test runner + render snapshots of both surfaces. See the test-runner setup notes.

## Note

jsdom snapshots (had they stayed) capture DOM/classes, not computed CSS — this was a CSS-namespace refactor, so it still warrants a visual check of the Brief detail drawer and the Matrix read pane. The live `web` compose container serves master, so verify against a dev server pointed at this worktree.
