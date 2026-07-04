## System λ: methods (0049 S4.3)

The congestion column for each method is `lmps − ref`, where `ref` is that
method's per-snapshot scalar. The reason we produce several methods is not that
we intend to *pick* one — we already have a principled choice — but that each
approximation lets us stress-test the principled λ from a different angle. Frame
the columns as **the fixed model reference plus a set of approximations of it**,
not as a competition.

**Fixed model reference (headline).** `system_lambda_merit_order` is the
copper-plate λ recovered via merit-order economic dispatch: on the Pass-1 solved
network, freeze at-bound real gens at their Pass-1 dispatch and shed gens at 0,
sort the remaining free real gens by marginal cost, and ramp cheapest-first
until residual load is met. The straddling gen's marginal cost is λ. This is
mathematically equivalent to the disabled `lambda_copper_plate` (a Pass-2 LP
with lifted line capacities) but skips the LP solve — milliseconds instead of ~3
s per snapshot. Full derivation and cross-validation:
[`compute/experiments/system_lambda/README.md`](../compute/experiments/system_lambda/README.md).
Interpret it as the *energy component* of LMP with all congestion premium
removed; it is not a congestion-weighted central price.

**External validator.** The real published λ (ERCOT NP4-523-CD,
`dam_system_lambda`) is joined into ERCOT-side records as `system_lambda`. On
the model side that column is always None — there is no model-side counterpart.
NP4-523-CD is the comparator we trust the model against, not a method the model
produces.

**Approximations, all model-side.** Kept as diagnostic side-by-sides.

| Column              | How it's derived                                                                                                | Read                                                                                        |
|---------------------|-----------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| `hub_avg`           | LMP at `HB_BUSAVG`, itself the mean over the k=200 buses nearest that hub centroid                              | Hub-anchored comparator; carries the hub k-nearest sampling choice                          |
| `load_weighted`     | Load-weighted mean LMP across all buses                                                                         | Biased high when heavy-load buses are congested imports                                     |
| `gen_weighted`      | Dispatch-weighted mean LMP across all buses                                                                     | Biased toward the export-constrained (cheap) side when the marginal fleet clusters          |
| `lmp_median`        | Median of solved bus LMPs                                                                                       | Robust, cheap, distribution-shape sensitive; historical placeholder                         |
| `system_lambda_kkt` | KKT/PTDF decomposition; median λ̂_i over the clean-bus set (≥1 dispatching unbound real gen, shed gens excluded) | **Experimental — do not use as reference.** See disposition below.                          |
| `simple_mean`       | `lmps.mean()`                                                                                                   | Not an approximation of λ; kept purely as the centering sanity check for the compute module |

### `system_lambda_kkt` disposition

Kept in `METHODS` but **treated as experimental / diagnostic only** — do not use
it as a reference or headline number. On the Texas2k static smoke
(`compute/experiments/system_lambda/README.md`) it was YELLOW with a max
residual of ~$128 vs the copper-plate λ; extended to the v1-120-postfix window
(post-shed-fix, post-k-nearest) the per-snapshot scalar ranges from −$78 to
+$1162 with std ≈ $200 and pairwise Pearson correlation of 0.06 with
`merit_order`, 0.06 with `system_lambda`. That is not usable as a scalar
reference at Texas2k scale.

The residual is not a scan gap — root-causing is documented in
`compute/experiments/system_lambda/README.md` ("Diagnostic record — what the
residual is NOT"). The identity holds in exact arithmetic; PyPSA's PTDF
construction plus HiGHS's dual-basis choice at 2,751 buses lose enough precision
to leave a per-bus bias that concentrates at extreme-LMP buses. Fixing this
would require either a higher-precision PTDF or steering HiGHS's basis choice;
both are out of scope for the pipeline.

The column stays in `METHODS` so consumers can still surface it for diagnostics
and so the numbers stay visible if we ever re-attack the PTDF precision issue;
the doc / consumer contract is that `merit_order` is the model reference and
`kkt` is a research column.

### External-λ range check

Full-window (`2025-01-01`..`2026-07-01`, 13,078 hourly DAM rows) confirms the
plan hypothesis: 61.5% of hours sit in the $20-60/MWh baseline (median $24.66,
mean $32.27); the tails are consistent with real ERCOT events — 26 hours at
$500-2000 concentrated on 2026-01-26 (a winter cold snap), scattered
spring/summer $100-500 stress days, and 260 negative-λ hours clustered in
November 2025 and April 2026 (wind gluts). Details, per-day cluster tables, and
top/bottom hour lists:
[`compute/experiments/lambda_validation/dam_lambda_range.md`](../compute/experiments/lambda_validation/dam_lambda_range.md).

### Cross-method comparison

Side-by-side of every method above on the v1-120-postfix model window (with
NP4-523-CD `system_lambda` joined in as the external validator):
[`compute/experiments/lambda_validation/cross_method.md`](../compute/experiments/lambda_validation/cross_method.md).
The v1-120 window is a summer-peak stress sample, so almost every snapshot
activated shed; the shed-clean subset is only 1 record and will fill out in the
full-year re-backfill. Notable from the shed-tainted window: `merit_order` is
nearly pegged near ~$28.55 (mean 28.45, std 2.66) — the same free real gen
straddles residual load across most stress snapshots, so its marginal cost sets
λ repeatedly; `lmp_median` correlates best with NP4-523-CD (r = 0.82), `hub_avg`
next (r = 0.78), `merit_order` r = 0.37, `kkt` r = 0.06. Under stress the
model's LMP distribution tracks the published λ better than the pure energy
component does — expected since NP4-523-CD itself absorbs some scarcity premium.

DAM vs RT: we are working DAM (ERCOT publishes DAM system λ in NP4-523-CD;
that's the comparator). ERCOT-side structural stats are kept as diagnostic only.
