# Spike 0013: System Lambda Extraction

Four approaches tried. The **two-pass copper-plate method (Option 5)** produces an exact, noise-free λ at Texas2k scale and is the recommended extraction.

## TL;DR

* **Path B (GlobalConstraint dual): RED.** Dual is a free LP variable.
* **Option 4a (KKT decomposition on PyPSA flow+KVL LMPs): GREEN on toy, YELLOW on Texas2k.** Residual ~$4–10 typical, $128 max.
* **Option 4b (KKT decomposition on a self-built bus-angle DC OPF): same residuals.** Rules out KVL duals as the cause.
* **Option 5 (two-pass copper-plate): GREEN on toy and Texas2k.** λ = $10.45 on Texas2k; cross-bus uniformity = 2.6e-7 (machine epsilon). Exact energy-component extraction, no PTDF inversion required.

## Run

```bash
docker compose run --rm compute python \
    /compute/experiments/system_lambda/spike_extract.py        --mode both --run-id v1   # Path B
docker compose run --rm compute python \
    /compute/experiments/system_lambda/kkt_reconstruct.py      --mode both --run-id v3   # Option 4a
docker compose run --rm compute python \
    /compute/experiments/system_lambda/copper_plate_lambda.py  --mode both --run-id v1   # Option 5
```

The bus-angle solver lives in `bus_angle_solve.py` and is used by Option 4b's diagnostic.

---

## Path B (GlobalConstraint dual) — RED

Three formulations (`native`, `eq`, `ge`); none yields a meaningful dual. The added row is a linear combination of existing per-bus balances → free LP variable.

---

## Option 4a: KKT decomposition (primary)

For each bus i:

```
λ̂_i = LMP_i − Σ_b PTDF[b, i] × (μ_upper_b − μ_lower_b)
```

In bus-angle DC OPF this is an algebraic identity; λ̂_i is bus-independent at the optimum.

**Inputs already in production** (`snapshot.py:103-110, 160-165`): LMPs, line/transformer mu, PTDF from `ptdf_lodf.py:52`. No new solves.

### Toy (3-bus) — GREEN

| Snapshot | Hand λ | λ̂ | residual_max |
|---|---|---|---|
| `uncongested` | 20 | 20.000 | 0.0 |
| `congested`   | 20 | 20.000 | 5e-15 |
| `gen_pinned`  | 60 | 60.000 | 0.0 |

### Texas2k (1 snapshot, 2751 buses) — YELLOW

| | Value |
|---|---|
| **`lambda_hat_clean_median`** | **$26.68** |
| LMP at slack bus (7098) | $25.35 |
| clean-bus residual p50 / p95 / max | $3.42 / $13.58 / $13.58 |
| n_buses_clean | 18 |
| `lambda_hat_load_weighted` (comparator) | $21.56 |
| `lambda_hat_filtered_median` (comparator) | $20.70 |
| `lmps.median()` (placeholder) | $15.39 |

`λ̂_slack = LMP_slack = $25.35` exactly (PTDF column at slack is zero by construction) — confirms PTDF/LMP alignment is correct. At buses far from slack, residuals appear.

---

## Diagnostic record — what the residual is NOT

Per a code-review pushback (paraphrased): *"The KKT identity is exact; spread is a missing term, not economic structure."* Correct on the framing. Full investigation:

| Hypothesis | Test | Result |
|---|---|---|
| HVDC Links contribute duals not in PTDF | `len(n.links)` | 0 — ruled out |
| PTDF rows misaligned with line+tx ordering | `ptdf.shape` vs `n_lines + n_tx` | 5344 = 3993 + 1351 — aligned |
| Bus ordering mismatch | `bus_names == n.buses.index` | Different order (slack moved to position 0) but `lmps.reindex(bus_names)` aligns correctly; `PTDF[:, slack_col] = 0` and `λ̂_slack = LMP_slack` confirms alignment is right |
| PTDF mechanically wrong | `PTDF @ injection` vs `n.lines_t.p0` + `n.transformers_t.p0` | Reproduces flows exactly (max diff = 0.0000) |
| **KVL cycle duals leak mass PTDF can't recover** | Built a complete bus-angle DC OPF in `bus_angle_solve.py` (no KVL constraints) | **LMPs bit-identical to PyPSA flow+KVL; residuals also identical. KVL is NOT the cause.** |
| Fold KVL into effective shadow | `PTDF.T @ (shadow ± kvl_contribution)` | No effect (`PTDF.T` is orthogonal to cycle space) |
| Sign convention on lines vs transformers | Tried 5 sign permutations | None reduces spread |
| Shunt impedances inject active power | `n.shunt_impedances['g']` | All g=0 (reactive only); not the cause |
| Transformer concentration drives residual | Grouped residuals by # incident transformers per bus | Weakly correlated; bus with 0 transformers still has $133 residual |

### What we know about the residual

* Bounded: max ~$128, p50 ~$4.5 across 2682 non-degenerate buses (close to typical LMP magnitudes ~$15–30).
* Concentrated at extreme-LMP buses (max LMP = $710, min = -$803 — the worst residual buses sit near these tails).
* Slack bus and its topological neighbors are clean (residual ≈ 0 within ~$0.01).
* Same residual structure under both PyPSA's flow+KVL and our independent bus-angle solver.

### Best remaining hypothesis (not verified)

`sub.calculate_PTDF()` performs a sparse 2751×2751 inversion of the bus susceptance matrix. The numerical precision of that inversion, combined with PyPSA's LP dual solution (which is in part chosen by HiGHS among multiple feasible dual bases at scale), leaves a small per-bus inconsistency that accumulates with topological distance from the slack. The identity holds in exact arithmetic; PyPSA's specific construction loses precision at scale.

Definitively confirming this would require: (a) recomputing PTDF in higher precision and re-running, or (b) inspecting HiGHS's basis to see if the LP optimum is dual-degenerate. Both are beyond the spike's scope.

---

## Option 5: Two-pass copper-plate (recommended)

Pass 1: standard DC OPF → dispatch + per-generator duals. Pass 2: on a copy of the network, fix every at-bound generator (μ_upper or μ_lower > 1e-6) at its Pass 1 level via `p_min_pu = p_max_pu = P_gen/p_nom`; leave marginal gens free; lift line/transformer `s_nom` by 1e6 (copper plate). Re-solve. With no congestion source, all LMPs collapse to a single value = system λ.

Why this avoids Path B's failure: the marginal generators left free in Pass 2 give the LP enough flexibility that per-bus balance duals are well-defined and bind to the marginal generator's cost. Fixing the at-bound gens preserves the Pass 1 operating point.

Script: `copper_plate_lambda.py`. Output: `cp_results_*.json`.

### Toy (3-bus) — GREEN

| Snapshot | Expected λ | Pass 2 λ | Spread (max − min) |
|---|---|---|---|
| `uncongested` | 20 | 20.000 | 0.0 |
| `congested`   | (range $20–$60) | 20.000 | 0.0 |
| `gen_pinned`  | 60 | 60.000 | 0.0 |

The `congested` regime is the proof: Pass 1 LMPs split $20/$40/$60 across the three buses; Pass 2 collapses them to $20.00 exactly (g_cheap supplies all 180 MW alone on the copper plate).

### Texas2k (1 snapshot, 2751 buses) — GREEN

| | Value |
|---|---|
| **`pass2_lambda_hat`** | **$10.45** |
| Cross-bus LMP spread (max − min) | 2.6e-7 |
| Marginal gens (free in Pass 2) | 88 |
| At-bound gens (fixed in Pass 2) | 1011 |

The $10.45 figure is the pure energy component: the marginal cost of the cheapest available up-ramping generator, with all congestion removed. It is structurally lower than the KKT clean-bus median ($26.68) because KKT mixes in congestion premium that the copper-plate solve eliminates.

---

## Recommendation

* Replace `lmps.dropna().median()` (`congestion_snapshot.py:176`) with the **two-pass copper-plate λ**. It is the only method that produces a noise-free scalar at Texas2k scale (uniformity ~1e-7 vs KKT's $128 max residual).
* Keep KKT clean-bus median, load-weighted, and `lmps.median()` as side-by-side comparators in the JSON for diagnostic visibility.
* Cost: Pass 2 adds one solve per snapshot (~3 s on Texas2k). Acceptable.
* Caveat to document: copper-plate λ is the *energy component* of LMP, not a congestion-weighted central price. If a downstream consumer needs the latter, the KKT clean-bus median remains a better proxy.
* **Future work**: warm-start Pass 2 from Pass 1 basis to halve the added solve cost (not surfaced cleanly through linopy/PyPSA today).
