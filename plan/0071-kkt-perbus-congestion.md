# 0071 - kkt-perbus-congestion

Type: fix
Branch: fix/0071-kkt-perbus-congestion
Follows: 0070-matrix-dense-rectangle.md
Preceded by handoffs: handoff-congestion-matrix.md, handoff-congestion-matrix-tests.md

## Goal

* Add a `kkt_perbus` model-side congestion method sourced directly from
  `bus_snapshots.modeled_congestion` (= Σ PTDF · signed μ per bus).
* Eliminate the ~148-std hourly bus-mean common-mode that
  `LMP − system_lambda_merit_order` was injecting into `model_C`.
* Keep the pipeline able to write new run-ids without overwriting the
  ship-state `v1-annual` artifacts.

## Context

* On `v1-annual`, the default model-side reference was
  `system_lambda_merit_order` (copper-plate / uncongested λ). The ERCOT
  side used `system_lambda` (SCED power-balance dual, congested).
* Different definitions of "energy component" between the two sides →
  `model_C` carried a per-hour, bus-uniform scalar
  `(λ_congested − λ_uncongested)` that no per-bus congestion correlation
  could overcome. Scorecard headline:
  `rank_spearman=0.256 mean_corr=0.141`.
* The per-bus `Σ PTDF · signed μ` was already computed at snapshot time
  (`compute/congestion/metrics.py::modeled_congestion_at`) and persisted
  to `bus_snapshots.modeled_congestion`. By the KKT identity this is
  the model_C the matrix should have been reading all along.
* Sign convention for `modeled_congestion` was empirically verified on
  DFW `2025-08-19T19:00` (see `verify_sign_convention.py` and
  `metrics.py:33` `MU_SIGN`), so no sign flip is needed when the matrix
  reads it directly.

## Study — verification before touching the pipeline

Both checks run against the existing `v1-annual` artifacts + Postgres,
no re-solve. See `scratchpad/check_a.py` and `scratchpad/check_b.py` for
the exact scripts (piped to `compute-shell:/tmp/`).

### Check A — hourly bus-mean std of `modeled_congestion`

Pivot `bus_snapshots.modeled_congestion` to `(n_bus × n_hours)` over the
ship-state window (2594 buses × 7,816 hours), take axis-0 mean, then std.

**Result: std collapses from 148.5 → 13.28 (~11× reduction).**

* p1 = −44.6, p50 = −4.0, p95 = +1.9, p99 = +4.1, |max| = 244.
* Residual 13 (vs the 5.4 ERCOT floor) is a legitimate physical skew:
  the arithmetic bus-mean of Σ PTDF · μ isn't required to be zero unless
  buses are uniformly distributed around the network. The negative
  skew comes from scarcity hours where import-side buses dominate.
* This is a **PASS** — the KKT identity holds numerically well enough
  that `modeled_congestion` lives in the near-zero-mean subspace, so
  no sign / wiring / slack bug is hiding.

### Check B — regime breakdown of `merit_order − kkt`

Two scalars per hour from `snapshot_meta`; difference and dispersion:

| quantity                       | mean   | std    | min      | max      |
|--------------------------------|--------|--------|----------|----------|
| `system_lambda_merit_order`    |  28.73 |   4.92 |          |          |
| `system_lambda_kkt`            | 145.29 | 260.71 |          |          |
| `mo − kkt`                     | −116.57 | 260.83 | −1451.28 | +3631.53 |

* `|mo − kkt| > $50` on **37.3%** of hours; `> $200` on **28.6%**.
* Regime bucketing degenerated because model-side `lmp_min` is very
  negative in nearly every hour (load-shed penalty). Aggregate stats
  already tell the story — the merit_order ref was subtracting a
  stable ~$29 while congested λ swung by hundreds.
* This is a **PASS** — the ~148 std the handoff measured on a shorter
  subset scales to ~260 std on the full year. Same shape.

## Approach

* Work in: `compute/matrix.py` and `compute/congestion/compute.py`.
* Entry point / primary change:
  `compute/matrix.py::build_model_matrices`.
* Step 1 — Add `kkt_perbus` to `METHODS` in
  `compute/congestion/compute.py`. It stays absent from the
  `compute_congestion()` computation path (no scalar reference to
  compute); comment marks it as model-side-only.
* Step 2 — In `build_model_matrices`, when `kkt_perbus` is in the
  requested `ref_methods`, extend the streaming `SELECT` to include
  `modeled_congestion`, widen the `WHERE` to `(lmp IS NOT NULL OR
  modeled_congestion IS NOT NULL)`, and set
  `model_C["kkt_perbus"][i, j] = modeled_congestion[bus, ts]` directly
  (skip the scalar-ref subtraction).
* Step 3 — In `main()`, refuse `--run-id v1-annual` outright so a
  re-run cannot clobber the ship-state artifacts.
* Do NOT touch: `compute/congestion/metrics.py::modeled_congestion_at`
  (its sign convention has been empirically verified and is what the
  new method depends on).
* Do NOT touch: the ERCOT-side matrix. `system_lambda` stays as the
  congested-reference on that side.

## Acceptance

* [x] `METHODS` includes `kkt_perbus`.
* [x] `matrix.py::build_model_matrices` fills `model_C["kkt_perbus"]`
      from `bus_snapshots.modeled_congestion`, not from
      `lmp − ref_scalar`.
* [x] `matrix.py::main()` raises SystemExit when `--run-id == "v1-annual"`.
* [x] Files sync clean to `compute-shell:/compute/` (md5 match).
* [x] `python -m matrix --run-id v1-annual-kkt --dates-file
      sample_specs/flat_dates_2025-01-01_2026-01-01.json` runs and
      writes `runs/v1-annual-kkt/matrix/congestion_matrices.npz`
      (2594 buses × 964 SPs × 7816 hours, matching v1-annual geometry).
* [x] `correlation_map --model-ref kkt_perbus --ercot-ref system_lambda`
      lifts median_corr materially — **PARTIAL**: 0.232 → 0.297,
      matching the `load_weighted × load_weighted` proxy (0.298) as
      the handoff predicted the tests would.
* [x] Winner-concentration drop — **NOT MET**: still 73 distinct
      winners for 964 SPs, top-3 (1020 / 8052 / 1124) claim 41.9%.
      p99 ceiling only nudges from 0.52 → 0.502, max 0.521.
      `pct>0.5` is only 1.0% (vs 10.7% for the load_weighted proxy).
      Falsifies the handoff hypothesis that common-mode removal alone
      would scatter the winners; residual is zonal (see next-steps
      handoff).
* [x] `scorecard --ref kkt_perbus --algo hierarchical_on_beta --k 6`
      re-run on `v1-annual-kkt`: all three thesis metrics up vs
      `v1-annual`. `rank_spearman` 0.256 → **0.298** (+16%),
      `mean_corr` 0.141 → **0.194** (+38%),
      `mean_sign_agreement` 0.575 → **0.648** (+13%). No NaN-handling
      warnings on any downstream stage.

## Result & interpretation

The common-mode fix does exactly what Checks A/B guaranteed. Median
correlation lifts (0.232 → 0.297) in line with the scalar common-mode
removal, and all three thesis metrics on the scorecard move up together
(rank_spearman +16%, mean_corr +38%, sign_agreement +13%). Two extra
diagnostics from `basis_regression` corroborate that this is real
structural improvement, not noise:

* PCA k rose from 2 → 4 to hit the same 90% cumvar target — the shared
  variance is now spread across more real components instead of
  concentrated in the common-mode axis.
* `r2_bus_median` dropped from **0.99 → 0.70**. Under merit_order every
  bus was ~99% explained by the shared PCs because they all projected
  onto the common-mode; under kkt_perbus, the top-4 PCs capture 70% of
  a typical bus's variance and the remaining 30% is bus-level structure
  that was previously buried.

What did NOT change: the tail (`pct>0.5` = 1%, p90 = 0.428) is
materially weaker than `load_weighted × load_weighted` (10.7%,
p90 = 0.502), and winner concentration is essentially unchanged
(73 vs 75 distinct winners, top-3 41.9% vs 42%).

**Reading**: the algebraic common-mode from mismatched refs is gone,
but the "few buses win everything" pattern is NOT primarily driven by
it. A residual zonal-level component still syncs a small set of model
buses to many SPs. `load_weighted` incidentally cancels that
symmetrically (both sides subtract a load-weighted average of their
own prices); `kkt_perbus × system_lambda` doesn't.

This lines up with the tests handoff's second-order recommendation
(zone-local reference). Follow-up: see
`plan/handoff-congestion-matrix-next-steps.md` for the prioritized
plan — subtract a per-load-zone reference (Houston / North / South /
West hub or load-weighted zone mean) so the zonal component cancels
symmetrically on both sides. The KKT fix should stay — it is the
algebraically correct model-side congestion — but by itself it is
insufficient to lift the tail.
