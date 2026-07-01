# B3 - sample-recompute-gate

Type: chore
Branch: chore/sample-recompute-gate

## Goal

* Recompute the ~20 sample snapshots in `compute/sample_specs/reference_dates_120.json` (or summer-peak subset) with the new metrics writing to DB.
* Spot-check three representative snapshots against OPF duals by hand.
* Produce a go/no-go decision doc for the full-year recompute.

## Context

* This is the last cheap check before spending full-year compute (§3.10 of sprint2a-plan.md).
* Depends on B1 + B2 landed and migration 18 applied.
* Not a code change - a runbook + written verification. Could fold into B2 if reviewer prefers.

## Approach

* Work in: `compute/sample_specs/`, `docs/`
* Run: `python -m compute.write_snapshots --specs compute/sample_specs/reference_dates_120.json --force-recompute` (or the summer-peak subset if runtime is prohibitive).
* Spot-check three snapshots by hand:
  * `2025-08-19T19:00` - DFW summer-peak (documented in `docs/phase-3-analysis.md`).
  * One high-wind west hour.
  * One mild shoulder hour.
* For each, SELECT from `bus_snapshots` + `snapshot_meta` and confirm:
  * `modeled_congestion` has both signs across the bus population.
  * `binding_proximity ≈ 1.0` for lines flagged in `binding_lines`; ≤ 1.0 (+ solver tolerance) elsewhere.
  * DFW: import-side buses (north_central weather zone, highest LMP) carry positive `modeled_congestion`.
* Write `docs/sample-recompute-gate-results.md` with the SELECT outputs, signs observed, and a go/no-go verdict.
* Do NOT proceed to full-year (B4) if any of the three checks fails - iterate on B1's metric or sign convention.

## Acceptance

* [ ] All sample snapshots have `status='ok'` after recompute; new columns populated on each.
* [ ] `docs/sample-recompute-gate-results.md` exists with three snapshot verifications and an explicit "GO" or "NO-GO".
* [ ] DFW `2025-08-19T19:00`: north_central buses show positive `modeled_congestion`; documented with SELECT output.
* [ ] `binding_proximity` values for lines in `binding_lines` fall in [~0.98, ~1.02]; no non-binding line exceeds ~1.0.
