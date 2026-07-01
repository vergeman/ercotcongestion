# B5 - events-and-grep-gate

Type: chore
Branch: chore/0041-events-and-grep-gate

## Goal

* Update `web/src/lib/events.ts` — swap `suggested_view: "fragility"` occurrences to `"modeled_congestion"` (or `"lmp"` where a negative-price event reads better in LMP), and rework the "does fragility light up..." copy to reference modeled congestion + export-constrained corridors.
* Run the grep gate — `grep -rn "fragility\|frag" web/src/` must return 0 hits — and land any final trailing string / dead CSS var cleanup surfaced by the sweep.
* Run the manual verification checklist from sprint2c-plan.md §3.14 against a Sprint-0 sample DB and record the pass in the PR description.

## Context

* Depends on 0037-0040 all landed. This branch is the last-mile sweep + verification gate for the sprint2c umbrella.
* Small by design — housekeeping only. If the grep surfaces a non-trivial rewire (a component nobody touched in 0037-0040), stop and open a follow-up branch rather than expanding scope here.
* Verification is a checklist, not a code task; it must be executed against a running app, not asserted from types.

## Approach

* Work in: `web/src/lib/events.ts` (primary), then whichever files the grep sweep surfaces (expected: 0)
* `web/src/lib/events.ts`:
  * Lines 37, 61: `suggested_view: "modeled_congestion"`. Exception: if an event is explicitly about negative pricing (grep for `negative`, `oversupply`, `curtailment` in the event copy), leave it on `"lmp"`.
  * Line 45 copy: replace "does fragility light up..." with "does the modeled congestion light up the export-constrained corridors?"
  * Any other in-file `fragility` reference — rewrite in the same voice.
* Grep sweep:
  * `grep -rn "fragility\|frag" web/src/` — expect 0 hits.
  * If hits remain, fix in-branch when trivial (stale comment, dead import), otherwise document them in the PR description and file a follow-up.
  * Also grep `--frag` across `web/` to catch any CSS var stragglers.
* Manual verification (execute against running API + Sprint-0 sample DB, record outcomes in PR body):
  1. Load 2025-08-19T19:00 (DFW summer-peak). Modeled congestion view: north_central buses strongly positive (red); west buses near-zero / blue.
  2. Binding proximity view: DFW L15xx/L20xx-adjacent buses in the top band; slack corridors dim.
  3. Congestion-vs-basis view: sign-agreement visually tracks the ValidationPanel's ρ / sign-agreement number.
  4. Playback across a Sprint-0 window: swapping views does not blank the map, no console errors, legend updates on each swap.
  5. No stray `fragility` string in any panel, tooltip, header, or event card.
* Do NOT touch: anything the sweep does not surface. This branch is not a refactor pass.

## Acceptance

* [ ] `grep -rn "fragility\|frag" web/src/` returns 0 hits.
* [ ] `grep -rn "\-\-frag" web/` returns 0 hits.
* [ ] `web/src/lib/events.ts` `suggested_view` values point at `modeled_congestion` (or `lmp` where semantically appropriate); event copy is fragility-free.
* [ ] Manual §3.14 checklist executed against a Sprint-0 DB; outcomes recorded in the PR description with the snapshot timestamps used.
* [ ] No console errors observed when sweeping all four `ViewMode` values on a Sprint-0 snapshot during the checklist run.
