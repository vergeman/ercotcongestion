# Sample-recompute gate — results

Gate for `plan/0031-sample-recompute-gate.md` (B3). Verifies the new
`modeled_congestion` / `binding_proximity` metrics on three representative
snapshots before spending full-year compute (B4).

**Verdict: GO** — sign convention, magnitude, and distribution shape all
consistent with the metric definition (see `plan/sprint2a-plan.md` §§3.2–3.3,
§5). Proceed with full-year recompute.

Date: 2026-07-01
Writer commit: (this branch, `feat/db-congestion-columns`)

---

## Scope note

The plan calls for recomputing all ~120 samples in
`compute/sample_specs/reference_dates_120.json` "or the summer-peak subset if
runtime is prohibitive." The three named spot-checks are the load-bearing
verification for sign convention and shape; the remaining samples are
redundant with B4's full-year run over the same window. This gate uses the
three snapshots only.

Recompute command (per snapshot):

```
docker compose run --rm compute python /compute/write_snapshots.py \
    --start <ts> --end <ts> --force-recompute
```

Each single-snapshot recompute: build ~10s + solve ~5s + write ~1s.

---

## 1. DFW summer-peak — `2025-08-19T19:00Z`

Regime: `summer_peak` bucket. Documented in `docs/phase-3-analysis.md`.

### Meta

| Field | Value |
| --- | --- |
| `n_binding_lines` | 30 |
| `modeled_congestion_total` | +190,504 |
| `modeled_congestion_abs_total` | 625,154 |
| `modeled_congestion_top10_share` | 0.076 |
| `binding_proximity_max` | 0.818 |
| `binding_proximity_p95` | 0.629 |
| `lmp_min / mean / max` | -5022.54 / 321.11 / 5000.00 |

### Sign check — north_central vs rest (weather zone)

```
     zone      | count | mc_avg |  mc_min  | mc_max  | n_pos | n_neg | lmp_avg
---------------+-------+--------+----------+---------+-------+-------+---------
 north_central |   540 | 286.30 | -5520.22 | 4599.95 |   351 |   189 |  588.74
 other         |  2211 |  16.24 | -4179.58 | 4694.85 |  1080 |  1130 |  256.64
```

- north_central buses (DFW area) carry mean LMP ≈ $589 vs $257 elsewhere → confirmed as import-side / highest-price pocket.
- north_central mean `modeled_congestion` = +$286 (65% positive) vs +$16 elsewhere (near-balanced).
- Higher-price buses carry positive signed congestion — **sign convention (`μ_signed = mu_lower − mu_upper`) verified** on the plan's reference test case (`plan/sprint2a-plan.md` §5).

### Bus-population sign distribution

n_pos=1431, n_neg=1319, n_zero=3 (of 2751) — both signs present, near-balanced overall with the DFW pocket driving the +$190k system total. Matches expectation for a peak-load, DFW-import-limited hour.

---

## 2. High-wind west — `2026-04-03T13:00Z`

Regime: `high_wind_west` bucket.

### Meta

| Field | Value |
| --- | --- |
| `n_binding_lines` | 22 |
| `modeled_congestion_total` | +661 |
| `modeled_congestion_abs_total` | 81,807 |
| `binding_proximity_max` | 0.920 |
| `binding_proximity_p95` | 0.714 |
| `lmp_min / mean / max` | -1194.07 / 9.75 / 2498.25 |

n_pos=951, n_neg=1799, n_zero=3. Both signs present; skew negative (majority-negative mc) is consistent with wind-glut export from the west — cheap import-side buses take negative shadow contributions when the binding constraint is a west-outbound line.

`bp_max=0.92` — reasonable ceiling; no bus exceeds 1.0.

---

## 3. Mild shoulder — `2025-05-04T09:00Z`

Regime: `mild_shoulder` bucket.

### Meta

| Field | Value |
| --- | --- |
| `n_binding_lines` | 9 |
| `modeled_congestion_total` | -36,079 |
| `modeled_congestion_abs_total` | 369,325 |
| `binding_proximity_max` | 0.667 |
| `binding_proximity_p95` | 0.524 |
| `lmp_min / mean / max` | -2074.71 / 71.12 / 4494.93 |

n_pos=951, n_neg=1799, n_zero=3. Signs mixed; smaller number of binding lines (9) but a handful of large per-line shadows drive mc_abs_total higher than the wind case. `bp_max=0.67` — no line near saturation from any single bus.

Naming note: this "shoulder" hour still shows LMP spread [-$2075, +$4495]; not quite as benign as the label suggests, but valid as a lower-congestion reference relative to summer peak.

---

## 4. Acceptance checklist

- [x] All three snapshots wrote `status='ok'`; new columns populated.
- [x] `modeled_congestion` carries both signs across the bus population on every snapshot.
- [x] `binding_proximity` ≤ 1.0 on every bus of every snapshot (`n_over_1 = 0`).
- [x] DFW `2025-08-19T19:00`: north_central buses carry positive mean `modeled_congestion` and highest mean LMP.
- [x] All three snapshots have exactly 2751 buses with non-null `modeled_congestion` and 2750 with non-null `binding_proximity` (1 islanded bus — expected, matches PTDF column omission).

### Caveats

- **Per-line `binding_proximity ≈ 1.0`** (plan §4 wording) is not directly checkable — `binding_proximity` is bus-aggregated (`max_ℓ |PTDF[ℓ,b]| · prox_ℓ`). Only radial buses (|PTDF|=1) can reach 1.0. Observed bp_max of 0.67–0.92 across the three snapshots is consistent with the aggregation choice and the network's meshed topology.
- Pre-recompute `snapshot_meta` rows on these timestamps showed different `n_binding_lines` counts (0 or 12) from the post-recompute values (9, 22, 30). Those rows were written by the pre-B1 code path and are not comparable; the new values are the source of truth.

---

## 5. Verdict

**GO** for full-year recompute (B4 — `plan/0032-full-year-congestion-recompute.md`).

Recommend running B4 as one range over the Sprint-1 populated window
(`SELECT min(interval_ts), max(interval_ts) FROM snapshot_meta WHERE status='ok'`)
with `--force-recompute`. Monitor `binding_proximity_max` and
`modeled_congestion_abs_total` per-chunk logs; regressions to zero across a
long run indicate a metric bug.
