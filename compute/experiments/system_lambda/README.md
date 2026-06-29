# Spike 0013: System Lambda Extraction

**Verdict: RED.** PyPSA 1.2.2 + HiGHS does not yield a usable system λ via an added global power-balance constraint. Keep the `lmps.median()` placeholder in `congestion_snapshot.py:176` (Path A).

## Run

```bash
docker compose run --rm compute python \
    /compute/experiments/system_lambda/spike_extract.py --mode both --run-id v1
```

## What was tried

Three formulations, each solved twice (vanilla vs with-constraint) on a 3-bus toy and one Texas2k snapshot:

| Mode | Formulation |
|---|---|
| `native` | `n.add('GlobalConstraint', type='primary_energy', sense='==', constant=0)` |
| `eq`     | linopy `Σ Generator-p == Σ p_load` (with `presolve='off'`) |
| `ge`     | linopy `Σ Generator-p >= Σ p_load` |

## Results

Toy (3 snapshots, hand-expected λ = 20 / [20,60] / 60):

| Mode | dual | notes |
|---|---|---|
| `native` | not exposed | `global_constraints_t` has no `mu` for this type |
| `eq` | infeasible | HiGHS rejects degenerate redundancy (even presolve off) |
| `ge` | 0.0 | constraint is slack from solver's view |

Texas2k (vanilla LMPs: p50 $15.39, range -$803 to $710):

| Mode | extracted λ | primal unchanged? |
|---|---|---|
| `native` | not exposed | yes |
| `eq` | $4.28  | no — LMPs shift by $4.28 |
| `ge` | $27.10 | no — LMPs shift by $27.10 |

## Why it fails

The added row is a linear combination of the per-bus nodal balances (their sum). Its dual is a free LP variable, so HiGHS picks 0 (`ge`) or an arbitrary gauge shift (`eq`); PyPSA's `primary_energy` doesn't encode per-snapshot balance at all.

A clean λ would require dropping a nodal balance and adding a reference-bus slack — a structural reformulation, not a wrapper.

## Next

Commit to Path A. Use `load_weighted` / `gen_weighted` references in `compute_congestion` (`congestion.py:25-32`) as Phase 4 robustness checks.
