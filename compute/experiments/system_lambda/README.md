# Spike 0013: System Lambda Extraction

Two approaches tried. Option 4 (KKT reconstruction) works; the original GlobalConstraint path doesn't.

## TL;DR

* **Path B (add a GlobalConstraint to PyPSA, read its dual): RED.** The dual is a free LP variable.
* **Option 4 (post-process LMPs + branch shadows via PTDF): GREEN on toy, YELLOW on Texas2k.** Primary scalar is `lambda_hat_clean_median` — median of λ̂_i restricted to buses with ≥1 unbound dispatching generator (where the decomposition is exact).

## Run

```bash
docker compose run --rm compute python \
    /compute/experiments/system_lambda/spike_extract.py    --mode both --run-id v1   # Path B
docker compose run --rm compute python \
    /compute/experiments/system_lambda/kkt_reconstruct.py  --mode both --run-id v2   # Option 4
```

---

## Path B: GlobalConstraint dual (RED)

Three formulations, each solved vs vanilla:

| Mode | Formulation |
|---|---|
| `native` | `n.add('GlobalConstraint', type='primary_energy', sense='==', constant=0)` |
| `eq`     | linopy `Σ Generator-p == Σ p_load` (`presolve='off'`) |
| `ge`     | linopy `Σ Generator-p >= Σ p_load` |

Toy (3 snapshots): `native` exposes no `mu`, `eq` infeasible, `ge` dual = 0. Texas2k: `eq`/`ge` return non-zero duals exactly equal to a uniform LMP shift — gauge artifact, not λ.

**Why**: the added row is a linear combination of the per-bus nodal balances. Its dual is a free variable HiGHS resolves arbitrarily.

---

## Option 4: KKT reconstruction

For each bus i, invert the DC OPF LMP decomposition:

```
λ̂_i = LMP_i − Σ_b PTDF[b, i] × (μ_upper_b − μ_lower_b)
```

Branches `b` = lines + transformers (PTDF rows ordered that way per `ptdf_lodf.py`). At a bus where a generator dispatches **inside** its bounds, KKT gives `λ̂_i = c_g` exactly — the system marginal cost. At a bus where the marginal gen binds at p_max, λ̂_i = c_g + ν_g (effective cost including scarcity rent), bus-specific.

**Inputs all already in the production pipeline** (`snapshot.py:103-110, 160-165`): no new solves.

### Aggregator

* **Primary** — `lambda_hat_clean_median`: median over buses with ≥1 generator satisfying `|mu_upper| < 1e-6 ∧ |mu_lower| < 1e-6 ∧ p > 1e-3`. This is the set where λ̂_i = c_g cleanly.
* **Comparators** — `lambda_hat_load_weighted`, `lambda_hat_filtered_median`, `lmps.median()`.

### Toy (3-bus, hand-checkable) — GREEN

| Snapshot | Hand λ | λ̂ | residual_max |
|---|---|---|---|
| `uncongested` | 20 | 20.000 | 0.0 |
| `congested`   | [20, 60] | 20.000 | 5e-15 |
| `gen_pinned`  | 60 | 60.000 | 0.0 |

Decomposition is exact at machine precision. Clean filter is a no-op (toy has too few buses for it to discriminate).

### Texas2k (1 snapshot, 2751 buses) — YELLOW

| | Value |
|---|---|
| **`lambda_hat_clean_median`** | **$26.68** |
| clean-bus residual p50 / p95 / max | $3.42 / $13.58 / $13.58 |
| n_buses_clean | 18 |
| `lambda_hat_load_weighted` (comparator) | $21.56 |
| `lambda_hat_filtered_median` (comparator) | $20.70 |
| `lmps.median()` (placeholder) | $15.39 |
| filtered-bus distribution p5 / p50 / p95 | $13.58 / $20.70 / $28.22 |

The clean-bus distribution (n=18) spans $13.10 → $31.07, suggesting this snapshot has **regionally distinct marginal generators** — transmission constraints prevent a single MC from setting price everywhere. The median $26.68 is a reasonable system marginal; the spread is real economic structure, not numerical noise.

The clean set is small (18 / 1099 generators) because:
* Renewables sit pinned at p_max with `marginal_cost = 0` (binding upper).
* Off-cost gas sits at p = 0 (binding lower).
* Only mid-merit thermal in active dispatch falls into the "strictly interior" band.

---

## Recommendation

* Promote `lambda_hat_clean_median` to primary `system_lambda` in `congestion_snapshot.py:176`.
* Keep `lmps.median()`, load-weighted, and filtered-median as side-by-side comparators in the JSON — they're cheap to compute and useful for cross-checking.
* Reuse `kkt.reconstruct_lambda` (this directory) as the pure function; `compute_snapshot_batch` already returns the needed inputs.
* Document the clean-bus distribution as a model-health diagnostic: when the spread is wide, the system is regionally segmented and a single scalar λ under-represents the reality.
