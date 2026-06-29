# Spike 0013: System Lambda Extraction

Three approaches tried. None produces an exact extraction at Texas2k scale; the KKT/PTDF approach gives a usable robust estimator.

## TL;DR

* **Path B (GlobalConstraint dual): RED.** Dual is a free LP variable.
* **Option 4a (KKT decomposition on PyPSA flow+KVL LMPs): GREEN on toy, YELLOW on Texas2k.** Residual ~$4–10 typical, $128 max.
* **Option 4b (KKT decomposition on a self-built bus-angle DC OPF): same residuals.** This rules out KVL duals as the cause — bus-angle and flow+KVL give bit-identical LMPs.
* **Root cause of the Texas2k residual is not fully pinned down** after testing every plausible hypothesis. The `lambda_hat_clean_median` is a **robust estimator**, not an identity-based extraction.

## Run

```bash
docker compose run --rm compute python \
    /compute/experiments/system_lambda/spike_extract.py    --mode both --run-id v1   # Path B
docker compose run --rm compute python \
    /compute/experiments/system_lambda/kkt_reconstruct.py  --mode both --run-id v3   # Option 4a
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

## Recommendation

* Replace `lmps.dropna().median()` (`congestion_snapshot.py:176`) with `lambda_hat_clean_median`. It's better than the median placeholder (uses information from line/transformer shadows + PTDF) but **document it as a robust estimator**, not a principled extraction.
* Keep `lmps.median()`, load-weighted, and filtered-median as side-by-side comparators. The spread across these is itself a diagnostic.
* Surface `kvl_diagnostic` and per-snapshot residual stats in the JSON output. When residual_max is small, the estimator is close to identity; when large, it's a soft aggregate.
* **Future work**: if a principled λ becomes necessary, implement a custom DC OPF with extended-precision PTDF or extract λ via a slack-bus reformulation. Neither is required for Phase 2.
