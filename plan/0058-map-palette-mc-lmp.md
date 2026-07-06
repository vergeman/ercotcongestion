# 0058 - map-palette-mc-lmp

Type: feat
Branch: feat/0058-map-palette-mc-lmp

## Goal

* Fix Modeled Congestion palette so mid-range values ($10–$100) are visibly
  distinct from noise instead of collapsing to cream.
* Give LMP a per-snapshot reference so its spatial pattern reads as
  "congestion-driven" rather than as "current price level."
* Add an ERCOT counterpart map — `SPP − system_λ` per settlement point — so
  Modeled Congestion has a direct visual baseline to validate against.

## Context

* Current MC palette in `web/src/lib/colors.ts:322-394` anchors on
  `p_high = P99(|mc|)` over the whole (bus × snapshot) window with `γ = 1.8`
  and `floor = 0.02 · p_high`. One heavily-binding hour lifts P99 enough
  that most buses at typical hours fall in the damped cream band —
  e.g. with P99 = $400, a bus at −$91 renders norm ≈ −0.055 (barely blue),
  a bus at +$36 renders norm ≈ +0.010 (cream).
* Within a single snapshot, LMP and MC maps look nearly identical because
  `LMP = system_λ + congestion + losses` and `system_λ` is spatially
  uniform — the across-bus pattern of LMP *is* the congestion pattern.
  This is a correctness signal, not a bug, but it means the LMP view adds
  no information beyond MC unless it exposes the temporal `system_λ` shift.
* LMP palette (`web/src/lib/colors.ts:39-46`, `LMP_PCT_LOW=0.01`,
  `LMP_PCT_HIGH=0.99`) centers cream on the window-wide median LMP, which
  is usually close to the window-average `system_λ`. A bus at
  `LMP = median + $10` in a high-λ hour looks orange on LMP but reads cream
  on MC — that discrepancy is the LMP palette encoding "expensive-vs-cheap
  in the window" rather than "congested-vs-not."
* No ERCOT counterpart to MC exists in the UI yet. The right quantity is
  `SPP − system_λ` (`dam_system_lambda`, NP4-523-CD, already ingested per
  `plan/0007-ercot-ingest-additional-data.md:13`). This is the ERCOT
  "congestion component" — not the shadow prices (per-line duals, wrong
  granularity) and not basis (`SPP − hub`, which zeroes out at the hub
  and hides signal in congested hub pockets).
* Units clarification: MC is $/MWh (correct — `μ_ℓ` is $/MWh, PTDF is
  dimensionless, so `Σ PTDF · μ` is $/MWh). No "leftover MWh" to fix.
* Existing "Congestion vs Basis" tab (`GridMap.tsx:647`,
  `Header.tsx:75-78`, `Legend.tsx:100`) has drifted from its original
  meaning and is a candidate for retirement or repurpose once Q3 lands.
  Details:
  * **Definition drift.** `compute/Basis.md:227-228` still describes
    `basis` as `LMP_bus − LMP_hub` from the model's own OPF (a same-OPF
    internal check). The code no longer does that. `snapshot.py:275-294`
    computes `basis = model_LMP_bus − ERCOT_zonal_LMP_zone(bus)`, and
    `backill_basis.py:112` reinforces it (`SET basis = bs.lmp - z.lmp`).
    The DB column is a cross-system delta (model minus ERCOT zonal), not
    the hub-relative same-OPF quantity the name and older docs imply.
  * **Contamination.** The current `basis` mixes true spatial congestion
    with calibration bias and topology asymmetry. `Basis.md:22-24` shows a
    +$8.15 median across ~4M rows; `Basis.md:105-112` shows Houston
    +$1.32 vs West +$13.42 — a wind × topology story, not congestion.
    Comparing MC (a clean spatial-congestion signal) against this basis
    is comparing signal against (signal + bias + topology error).
  * **What the map actually shows.** The tab renders
    `rank(mc) − rank(basis)` per bus (`computeCongestionVsBasisRank` in
    `GridMap.tsx:648`). Legend title: `Δ Rank (modeled congestion −
    basis)`. Rank-Δ dodges the magnitude bias but also loses the physical
    interpretation — it reads as "which side ranks a bus higher," not
    "is the modeled congestion component right." `Basis.md:249-262` calls
    for switching the headline metric to Spearman + sign-agreement and
    building an ERCOT-actuals column, which is exactly what Q3 delivers.

## Approach — decisions needed before implementation

Three design questions the user needs to answer. Each option below is
scoped so it can be built independently; picking one per question is enough
to unblock implementation.

### Q1. MC palette: preserve $/MWh magnitudes, or maximize spatial contrast?

* **Option A — tighten anchor + reduce γ (small fix).**
  Change `MC_PCT_HIGH: 0.99 → 0.90`, `MC_GAMMA: 1.8 → 1.2`, keep the
  rational tail. Same $/MWh = same shade property preserved. A $36 bus
  becomes visibly pale-blue/red. Outliers still ride the tail.
* **Option B — rank/quantile coloring (big fix).**
  Replace value→norm with `rank_in_window(v) → norm`, symmetric around
  the sign-flip point. Each snapshot uses ~equal amounts of each color.
  Maximum spatial contrast; loses "same shade = same $/MWh" — legend
  becomes "top 10% of imports," etc. Extremes need a saturated pin
  ("> P99") to stay visible.
* **Option C — mode toggle.**
  Ship both A and B behind a legend switch ("scale: $/MWh | rank").
  User picks per session. More UI work; lets the map answer both
  questions ("where is congestion" vs. "how is the pattern shifting").

### Q2. LMP palette: keep window-median center, or center on per-snapshot `system_λ`?

* **Option A — status quo (window-median cream).**
  LMP map reads as "how expensive across the whole window." Within a
  snapshot it duplicates MC's spatial pattern; across snapshots it shows
  the `system_λ` drift as a global brightness shift. Simplest to keep.
* **Option B — per-snapshot `system_λ` anchor (cream = system_λ this hour).**
  Every frame recenters so cream is that hour's `system_λ`. Blue = below
  system price (export side), orange = above (import side). LMP map now
  encodes the *sign-of-congestion* directly, matching MC's zero-anchored
  meaning. Trade-off: brightness no longer conveys time-of-day price level;
  a $200-λ hour and a $30-λ hour look the same at a flat-congestion bus.
* **Option C — two-channel palette (hue = sign vs. λ, luminance = |λ|).**
  Hue split around `system_λ` for the current hour; luminance encodes the
  hour's `system_λ` band itself. Preserves both temporal price level and
  spatial congestion pattern. Non-trivial to design so it stays legible.

### Q3. ERCOT counterpart map: build it, and if so, at what granularity?

* **Option A — settlement-point level (~1000 SPs).**
  Compute `SPP_sp − system_λ` per snapshot from `dam_spp` and
  `dam_system_lambda`. Render as a separate view mode alongside MC.
  Same palette family as MC so the two are directly comparable by eye.
  Won't overlay bus-for-bus on the TAMU grid (different topology) — a
  spatial-pattern comparison, not a per-node one.
* **Option B — zone-level (8 zones) or hub-level (5 hubs).**
  Aggregate `SPP − system_λ` by zone/hub. Coarser, but robust to
  settlement-point noise, and matches the resolution at which the
  validation story is already told (`compute/opf.md:196`).
* **Option C — skip for now.**
  Rely on the existing basis view (`SPP − hub`) as the ERCOT proxy.
  Simplest, but keeps the hub-cancellation blind spot noted in Context.

### Q4. Existing "Congestion vs Basis" tab: retire, repurpose, or leave?

Only meaningful if Q3 delivers an ERCOT counterpart. Otherwise this tab is
the closest thing to a validation view and should stay untouched.

* **Option A — retire once Q3 lands.**
  Delete the view-mode entry and its `computeCongestionVsBasisRank` path.
  The MC-vs-`SPP − system_λ` comparison from Q3 is a cleaner answer to
  the same question. Simplest end state; loses the (contaminated but
  historical) same-run comparison.
* **Option B — repurpose as MC-vs-ERCOT-congestion Δrank.**
  Keep the tab and the rank-Δ palette, but swap the `basis` input for
  the Q3 quantity (`SPP − system_λ` at bus's zone/SP). Now the tab
  answers the validation question — "where does modeled congestion rank
  agree with ERCOT's congestion rank" — with clean inputs. Also renames
  in `Header.tsx` and `Legend.tsx`.
* **Option C — leave as-is, add a docstring note.**
  Keep the current tab for now; add a comment in `snapshot.py:275` and
  `Basis.md` making the model-vs-ERCOT-zonal definition explicit so the
  next reader isn't misled by the hub-relative framing. Defer any
  redesign until Q3 has been in use for a bit.

### Implementation notes (once choices made)

* Work in: `web/src/lib/colors.ts`, `web/src/components/map/Legend.tsx`,
  `web/src/components/map/GridMap.tsx`, `web/src/App.tsx` (view-mode
  wiring).
* For Q3-A/B: add an API endpoint in `api/` reading `dam_spp` +
  `dam_system_lambda`; add a new `ViewMode` entry
  (`ercot_congestion`?) mirroring how `modeled_congestion` is wired
  through `App.tsx:250` and `GridMap.tsx:653`.
* Do NOT touch: the compute-side MC definition
  (`compute/README.md:412-422`), OPF write path, or DB schema.

## Acceptance

* [ ] User picks one option each for Q1, Q2, Q3, Q4; decisions recorded at
      the top of this file under a "Decisions" section.
* [ ] MC map on the sample run `/compute/runs/v1-3d`: a bus at |mc| = $50
      in a snapshot renders with a visibly non-cream color (not the
      current near-white).
* [ ] LMP map behavior matches Q2 choice: if B/C, cream point shifts with
      `system_λ` between snapshots on scrub; if A, no change from today.
* [ ] If Q3-A or Q3-B: new view-mode button in `Header.tsx` renders an
      ERCOT congestion map; legend title reads `SPP − system_λ ($/MWh)`;
      palette matches MC family so the two maps can be compared side-by-side.
* [ ] Q4 behavior matches choice: if A, "Congestion vs Basis" tab and
      `computeCongestionVsBasisRank` are removed; if B, tab renamed and
      input swapped to Q3 quantity; if C, no UI change but `snapshot.py`
      and `Basis.md` carry a note clarifying the current definition.
* [ ] Diagnostic script or notebook: for any snapshot in the window,
      `LMP_b − system_λ ≈ modeled_congestion_b` within a few $/MWh (losses
      tolerance) — confirms the identity that makes MC and LMP look alike
      within a frame is holding in the data.
