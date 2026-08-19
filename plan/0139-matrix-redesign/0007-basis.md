# 0006 - basis (node-vs-node congestion basis in the SF lens)

Type: feat
Branch: `feat/0139-matrix-redesign-0007-basis`
Source: `plan/0139-matrix-redesign/sprint-matrix-redesign.md`
Prototype: `docs/matrix_index_prototype.html` (the **SF lens → Nodes tab → "compare 2 rows ⇄"**
path; `nodeBasis()` / `compareBox()` are the reference reduction)
Depends on: 0001 (`/analysis/node` — full constraint column + μ for one settlement point),
0005 (the SF lens working-set, pins, selection model). No plan depends on this one.

## As built (deviation from the tray design below)

The docked-tray + shift-click design proved too cumbersome, so basis shipped as a **first-class
full-screen lens** instead:

* A third lens button **Basis** next to Detail / SF, **enabled only on the Nodes tab**; leaving the
  Nodes tab drops back to Detail.
* Slots **A** and **B** are filled by the **sidebar node search**: one click fills A, the next fills
  B (active slot advances A→B→A). Slot chips re-target; ⇄ swap and per-slot ✕ clear. Rows are
  badged A / B in the sidebar. No ghost, no shift-click, no grid gesture.
* Same decomposition content; μ follows the header **Data** toggle (Forecast μ / ERCOT DAM μ). The
  SIDE (mutual/one-sided) column was dropped — one-sidedness now reads from the `·` in the absent SF
  cell. `?lens=basis&sp_a=&sp_b=` deep-links a pair; old links resolve unchanged.
* Files: `lib/basis.ts`, `components/matrix/MatrixBasisPanel.tsx`, wiring in `MatrixWorkspace.tsx`,
  A/B badges in `MatrixSidebar.tsx`.

## Why

The SF lens already recovers, for any node, its full column of implied shift
factors × μ. Two of those columns are a **congestion basis**: `LMP_A,cong −
LMP_B,cong`, decomposed constraint-by-constraint. That is the one number implied
SF is *most* entitled to compute, since CRRs hedge the **congestion** component
only (energy and loss components never enter). It's a byproduct of data we
already ship, not a new subsystem.

It is a **niche** feature (not the general reader), so it must earn no top-level
real estate and add no new lens/mode. It rides entirely on selection inside the
SF lens.

## Product shape

A **basis tray** docked at the bottom of the SF lens (Nodes tab). Not a third lens, not a modal.

* **Slot A = the current selection.** Normal single-click still selects/previews a node exactly
  as in 0005; it just *also* fills slot A. No behavior change for anyone not using basis.
* **Slot B = an empty ghost** reading **"+ pick a second node to compare."** This empty slot is
  the entire advertisement — the feature is discoverable because the tray is always visible, and
  the empty B is a standing call-to-action. (This is the "empty space induces the comparison"
  idea, as a persistent dock rather than a pop-up that interrupts every click.)
* **Filling B is opt-in**, so ordinary clicking never hijacks a selection into a comparison:
  * click the empty B ghost → arms "pick B"; the next node click lands in B (cursor/hint shows
    the armed state), **or**
  * **shift/⌘-click** a node → fills B directly (power-user accelerator; never the only path).
* With A and B set, the tray expands into the decomposition (below). **Swap A⇄B** and **clear B**
  controls; clearing B collapses the tray back to the ghost. Changing the normal selection
  updates A and recomputes live against the held B.

Entry state: tray present but collapsed to the ghost (A pre-filled from whatever is selected,
B empty). Never blank, never modal.

## The decomposition (what the expanded tray shows)

For nodes A, B at the scrubbed hour, over **every** constraint `c` located on either node
(`SF[c,A]` or `SF[c,B]` present — a one-sided constraint still creates basis, so the sum must
include it, not just mutual ones):

```
contribᶜ = −(SF[c,A] − SF[c,B]) · μᶜ          # signed $/MWh added to (cong_A − cong_B)
basis    = Σ contribᶜ                          # = LMP_A,cong − LMP_B,cong
```

Table, ranked by |contrib|: `constraint · SF_A · SF_B · μ · basis $`. Rows where one side is
absent show `·` for that SF and are tagged **one-sided** vs **mutual**, so the user sees which
constraints both nodes share and which pull the basis apart. Header line: the signed `basis
$/MWh` total and **"N% of the basis is [top constraint]"** (the prototype's `share` readout).

* Reuse the SF-lens **value sub-toggle** (`SF | Forecast μ | ERCOT DAM μ`) for `μᶜ`: forecast-μ
  basis vs DAM-μ basis are both meaningful; DAM falls back to forecast when pending/partial, same
  rule as the rest of the lens.
* **Predicted vs realized** both available when the realized column exists (0001), so the tray
  can show the forecast basis and, once settled, the realized basis side by side.

### Sign / labeling

`basis` as defined is `cong_A − cong_B` (uses the app's `congestion adder =
−SF·μ`, consistent with `docs/SF.md` and the prototype). Label the two nodes
plainly as **A** and **B** with the swap control; **do not** hard-code a
source/sink settlement sign in v1 — surface the congestion-basis number and its
decomposition. Note the CRR-path framing in copy ("A→B congestion basis")
without asserting a settlement direction. Exact obligation/option sign is
deferred (see §Defer).

## Data honesty (must ship with the feature)

* This is a **congestion** basis only — implied SF carries no energy or loss component. State it.
* Show the reconciliation line already in the prototype: **"explains X% of settled basis"** when a
  realized basis is available, computed as `basis_implied / basis_settled`. If we can't compute a
  settled basis for the pair, say "congestion basis (implied SF)" and omit the %.
* Never imply the recovered SF is an official ERCOT PTDF (sprint invariant).

## Backend

**No new endpoint required.** A pair basis is two full node columns joined on constraint:

* Fetch `/analysis/node?sp=A` and `/analysis/node?sp=B` at the cursor hour (0001 already returns
  the full constraint column + μ, predicted and realized). Join client-side on constraint key,
  compute the reduction above.
* Cache the two node responses in the existing bounded frame/LRU layer keyed by
  `(sp, t, ws/we/span/run, val)` so sweeping A against a held B refetches only A.

*Optional, only if the two-call join proves heavy in practice:* add
`GET /analysis/basis?a=&b=&t=&val=` that does the join server-side and returns the ranked
`contrib` rows + total. Skip unless a profile says so — two `/analysis/node` calls are cheap and
keep the API surface flat.

## Frontend

* `web/src/lib/matrix.ts` (or a new `lib/basis.ts` if it stays self-contained): pure
  `nodeBasis(colA, colB, muByConstraint)` → `{ rows: [{constraint, sfA, sfB, mu, contrib,
  mutual}], total, topShare }`, ported from the prototype `nodeBasis()` (union of constraints,
  one-sided tagging, |contrib| sort). No change to the existing SF↔contribution math.
* `web/src/components/matrix/BasisTray.tsx` (new): docked tray — A slot (from selection), B ghost
  / picker, armed-pick state, swap/clear, expanded decomposition table, μ-source echo from the
  lens val-toggle, honesty line. Import/export color convention (color by −SF, and by sign of
  `contrib`) reused.
* `web/src/workspaces/MatrixWorkspace.tsx`: hold `basisB` (settlement-point id | null) +
  `pickingB` flag in workspace state; A derives from the existing selection. Wire the two
  `/analysis/node` fetches (reuse the node-detail fetch from 0003), feed `BasisTray`. Only mount
  the tray in the **Nodes tab / SF lens**; hidden in Read and in Constraints-tab (constraint pairs
  are not a basis).
* Shift/⌘-click handling on node rows in `MatrixGrid` sets `basisB` (accelerator); the ghost's
  "pick B" arms `pickingB` so the next plain click routes to B instead of selection.
* **URL:** add `?sp_b=` (the B node) so a pair is shareable — reuse `onSelectionRouteChange` /
  `withCoord`; A is the existing `?sp`. Absent `sp_b` = collapsed tray. Backward-compatible; old
  links (no `sp_b`) open collapsed.

## Steps (build order)

1. [x] `nodeBasis()` reduction ported to app types (union, one-sided, sign, total, top-share).
       Verified with a standalone script — repo has no test runner, so no formal test file.
2. [x] Full-screen `MatrixBasisPanel` (replaces `BasisTray`): slot chips, swap/clear, decomposition
       table, honesty line.
3. [x] Workspace wiring: `basisA`/`basisB`/`basisActiveSlot` state, two `/analysis/node` fetches +
       client join, Basis-lens-only mount, μ from the Data toggle.
4. [x] Sidebar click A → then B fill; `?lens=basis&sp_a=&sp_b=` route. (No shift/ghost gesture.)
5. [x] Verified via HMR + live 08-12 data (`basis == totalA − totalB`); owner eyeballed in browser.

## Do NOT touch

* `App.tsx` scrubber ownership / shared time cursor; the Read lens; the SF↔contribution + μ-source
  math in `lib/matrix.ts`; the import/export color convention; 0005's working-set / pin model
  (basis reads selection, it does not add a pin concept).
* ~~Do not add a top-level lens/mode or header button for basis.~~ Superseded — shipped as a Basis
  lens per owner (see **As built**).
* Never imply the implied SF is an official ERCOT PTDF.

## Acceptance

* [x] Basis is a Nodes-tab-only lens (button beside Detail/SF); Constraints tab disables it, Read/SF
      do not show it. (Full-screen lens, not a docked tray.)
* [x] Sidebar click fills A then B; swap A⇄B and per-slot clear work. (No ghost/shift-click.)
* [x] Decomposition ranks by |contrib|, shows `Shift Factor A/B · Shadow Price (μ) · Basis ($)`, the
      total, and top-constraint share; μ follows the Data toggle (DAM→forecast fallback); forecast +
      settled render when available. (Explicit mutual/one-sided tag dropped — `·` marks a one-sided SF.)
* [x] Honesty line present ("congestion basis (implied SF)", "explains X% of settled basis"); no PTDF claim.
* [x] `?lens=basis&sp_a=&sp_b=` deep-links a pair; old links resolve unchanged.

## Defer (do not build unless someone asks)

* Historical basis **time-series** / spread charts over the trailing window.
* **path-pair presets** or DAM auction-clearing overlays.
* **>2-node** baskets / portfolio basis.
* Exact **obligation vs option settlement sign** and source/sink labeling.

These are where a "basis tool" turns into a project. v1 stops at the single decomposed
two-node congestion basis off the existing selection gesture.
