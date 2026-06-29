# 0013 - system-lambda

Type: chore (spike)
Branch: experiment/0013-system-lambda

## Goal

* Determine if PyPSA can yield ERCOT-equivalent system λ via a redundant global power-balance dual.
* Toy 3-bus hand-verification + Texas2k smoke; green/yellow/red verdict.
* Decide Phase 2 path: dual-extracted λ (B) vs `lmps.median()` placeholder (A).

## Context

* Phase 2 needs `LMP − λ`; ERCOT publishes λ (NP4-523-CD), PyPSA does not.
* Today: `congestion_snapshot.py:176` uses `system_lambda = lmps.dropna().median()` (Path A).
* `compute_congestion` already wires a `system_lambda` reference column (`congestion.py:25-32`); no production code changes from this spike.

## Approach

* Work in: `compute/experiments/system_lambda/`
* Entry point: `spike_extract.py` (`--mode toy|texas2k|both`).
* Tried 3 balance formulations, each vs vanilla; compared primal + dual:
  * `native` — `n.add('GlobalConstraint', type='primary_energy', sense='==')`
  * `eq`     — linopy `Σ Generator-p == Σ p_load` (with `presolve='off'`)
  * `ge`     — linopy `Σ Generator-p >= Σ p_load`
* Do NOT touch: `congestion_snapshot.py`, `congestion.py`, any production code.

## Result

**Verdict: RED on both toy and Texas2k.** Commit to Path A.

* `native`: solves; PyPSA exposes no `mu` for this constraint type.
* `eq`: infeasible on toy (degenerate w/ KVL); on Texas2k extracts $4.28 but primal shifts by same constant — gauge artifact.
* `ge`: solves; dual = 0 on toy (slack from solver's view); on Texas2k extracts $27.10, again equals the LMP shift.
* Root cause: added row is a linear combo of per-bus nodal balances, so its dual is a free variable HiGHS resolves arbitrarily. A clean λ requires dropping a nodal balance + adding a slack injection at a reference bus — structural reformulation, out of scope.

## Acceptance

* [x] `spike_results_v1_toy.json` written (3 snapshots × 3 modes).
* [x] `spike_results_v1_texas2k.json` written (1 snapshot × 3 modes).
* [x] `README.md` with verdict + hand-vs-extracted table.
* [x] Re-runs are idempotent; no production code modified.
* [x] Follow-on: keep median placeholder; lean on `load_weighted` / `gen_weighted` references in `compute_congestion` for Phase 4 robustness checks.
