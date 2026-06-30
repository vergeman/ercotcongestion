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

**Path B verdict: RED.** Added row is a linear combo of per-bus nodal balances → dual is a free LP variable that HiGHS resolves arbitrarily.

* `native`: solves; PyPSA exposes no `mu` for this constraint type.
* `eq`: infeasible on toy (degenerate w/ KVL); on Texas2k extracts $4.28 but primal shifts by same constant — gauge artifact.
* `ge`: solves; dual = 0 on toy; on Texas2k extracts $27.10, equals the LMP shift.

## Follow-on: Option 4 (KKT/PTDF) — YELLOW

`kkt_reconstruct.py`. Decomposes λ from LMPs + line/tx shadows + PTDF. GREEN on toy (residual_max ~5e-15); YELLOW on Texas2k (clean-bus median = $26.68, max residual = $128). Bus-angle independent re-solve (`bus_angle_solve.py`) confirms KVL duals are not the cause; best hypothesis is sparse-PTDF inversion precision at 2751×2751 scale. Useful as a robust estimator, not as an identity.

## Follow-on: Option 5 (two-pass copper-plate) — GREEN

`copper_plate_lambda.py`. Pass 1 = standard DC OPF; Pass 2 = fix at-bound gens at Pass 1 dispatch, lift line/tx capacities by 1e6, re-solve. Uniform LMPs on the copper-plate Pass 2 = system λ.

* Toy: all three regimes match expected λ exactly; cross-bus spread = 0.
* Texas2k: **λ = $10.45**, cross-bus spread = 2.6e-7 (machine epsilon), 88 marginal gens / 1011 at-bound.

Interpretation: pure energy component of LMP, no congestion premium. Structurally lower than the KKT $26.68 because copper-plate removes congestion-driven dispersion across marginal gens.

**Recommended for production swap at `congestion_snapshot.py:176`** (separate PR). Adds one ~3 s solve per snapshot.

## Acceptance

* [x] `spike_results_v1_*.json` (Path B); `kkt_results_v3_*.json` (Option 4); `cp_results_v1_*.json` (Option 5).
* [x] `README.md` with all four approaches, results, and recommendation.
* [x] Re-runs idempotent; no production code modified in this spike.
* [ ] Production swap of `congestion_snapshot.py:176` to two-pass λ — separate PR.
