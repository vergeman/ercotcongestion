# B4 - validation-panel

Type: feat
Branch: feat/0040-validation-panel

## Goal

* Rewire `web/src/components/panels/ValidationPanel.tsx` to consume the 2B validation endpoint's signed × signed payload — signed modeled_congestion on x, signed basis on y, with a symlog transform on both axes.
* Rewrite the panel's narrative prose (lines 426, 457, 472, 489) around modeled congestion + direction, replacing the stale "fragility carries explanatory power" string called out in the handoff.
* Swap the `--frag-high` accent references to `--mc-accent` (defined in 0037) and update the correlation header + axis labels to match the endpoint semantics.

## Goal (payload)

* Draft copy for the ~line 472 region:
  > "Modeled congestion is the OPF's own congestion component — the signed `Σ PTDF·μ` at each bus. When the model says a bus is on the import side of a binding constraint (positive), the market's basis at that bus should also be positive (LMP above the zone reference). The ρ number answers 'does the model agree with the market, in sign and magnitude, when the grid is actually stressed?'"

## Context

* Depends on 0037 (renamed `ScatterPoint` type with signed `basis`) and 2B B2 (`feat/0035-validation-rewire`) shipping the signed-Pearson + `sign_agreement_*` fields.
* This panel is the sprint's narrative surface — the headline number moves from ρ ≈ 0.008 (retired fragility) to ρ ≈ 0.756 (signed × signed on 2025-08-19, per 2B acceptance). Prose must not undersell the shift.
* Symlog on both axes is the locked framing (per sprint2c-plan.md §5): `sign(x) * log10(1 + |x| / c)` with c ≈ 1 $/MWh; reference lines at axis zero + 45°/135° for the perfect-agreement quadrants.
* The `--frag-high` CSS var was renamed to `--mc-accent` in 0037; this branch is the only consumer left.

## Approach

* Work in: `web/src/components/panels/ValidationPanel.tsx`
* Line 17 axis-bounds comment: rewrite as "Symlog on both axes: sign(v) * log10(1 + |v|). Zero lines + 45°/135° perfect-agreement guides."
* Line 107 correlation header: `Correlation: modeled congestion vs basis (signed)`. Include the sign-agreement rate (`sign_agreement_overall`, `sign_agreement_congested`) alongside ρ.
* Lines 118, 150, 358: replace `var(--frag-high)` with `var(--mc-accent)` (accent/background/fill sites).
* Line 280 filter: `p.modeled_congestion !== 0 && p.basis !== 0` (drop the `> 0` magnitude gate — signed points on both sides are now valid).
* Line 283 log-mapping: replace `Math.log10(p.fragility)` with `Math.sign(p.modeled_congestion) * Math.log10(1 + Math.abs(p.modeled_congestion))`. Apply the same symlog to `p.basis` on the y-axis. Extract to a `symlog(v: number, c = 1)` helper local to the file.
* Add reference lines to the scatter:
  * x = 0 (vertical), y = 0 (horizontal).
  * y = x and y = -x diagonals (agreement / anti-agreement).
* Prose rewrites:
  * Line 472: use the draft copy above.
  * Lines 426, 457, 489: same voice — describe modeled_congestion as the OPF congestion component, note that direction matters, hedge on magnitude (screening tool, not P&L). Do NOT re-import "fragility" as a term.
* Add a small sign-agreement readout next to ρ: `sign-agreement: XX% overall, XX% congested`; null-guard if the endpoint returns null.
* Do NOT touch: types, colors, map, stats, sparkline, events (0037-0039, 0041 scope).

## Acceptance

* [x] `grep -n "fragility\|frag" web/src/components/panels/ValidationPanel.tsx` returns 0 hits.
* [x] Scatter renders signed modeled_congestion on x and signed basis on y using symlog (`sign(v) * log10(1 + |v|)` via a local `symlog` helper); filter drops only exact-zero points so all four quadrants are eligible.
* [x] Reference lines drawn at x=0, y=0, y=x, y=-x (bright zero lines + dashed 45°/135° guides).
* [x] Correlation header reads "modeled congestion vs basis (signed)" with a mono sign-agreement readout (`sign_agreement_overall` / `sign_agreement_congested`, null-guarded via `fmtSignAgreement`).
* [x] Line ~472 prose replaced with the draft copy; adjacent Interpretation branches rewritten in the same voice (direction first, magnitude as screening).
* [x] Accent driven by `--mc-accent` at all three sites (RhoTile, legend dot, congested scatter fill); no `--frag-*` var references remain in the file.
* [ ] With the API pointed at a Sprint-0 sample DB, the 2025-08-19T19:00 window shows ρ ≈ 0.756 and sign-agreement ≈ 0.575 in the panel header. _(pending in-app verification)_
