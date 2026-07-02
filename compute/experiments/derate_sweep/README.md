# Derate Sweep — Sprint 3

Sweeps the tied `(line_derate, tx_derate)` knob applied in
`apply_static_mutations` (`compute/operating_conditions.py`), on the Sprint-0
sample. Answers three questions: feasibility band, spatial rank stability
across the band, and which derate best matches observed basis. Signed
`modeled_congestion` throughout — never squared, never divided by headroom.

**Depends on:** Sprint 1 (zonal load geography) and Sprint 2 (signed metric).
Calibrating derate against basis on wrong load geography, or against the
retired `fragility` metric, tunes one error to compensate for another.

## Files

- `derate_sweep.py` — harness. `sample × DERATE_AXIS` → CSVs in `results/`.
- `derate_sweep_analysis.py` — reads the CSVs, prints the three reports.
- `results/`
  - `snapshot_summary.csv` — one row per `(ts, derate)`.
  - `bus_metrics.csv` — one row per `(ts, derate, bus)`: `modeled_congestion`,
    `binding_proximity`, `basis`.
  - `run.log`, `analysis.log` — captured stdout.

## Derate axis

Tied `(line, tx)` — transformers slightly looser than lines:

```
(1.00, 1.00), (0.95, 0.97), (0.90, 0.95), (0.85, 0.90), (0.80, 0.85)
```

## Running

```
docker compose run --rm compute python /compute/experiments/derate_sweep/derate_sweep.py
docker compose run --rm compute python /compute/experiments/derate_sweep/derate_sweep_analysis.py
```

Full sweep is 100 solves (20 ts × 5 derates), ~30–60 min single-snapshot
wall-clock.

## Results (first run, 2026-07-01)

### Feasibility

100% at every point 0.80 → 1.00. No lower feasibility edge inside the tested
band.

### Rank stability

Global `|MC|` ranking is stable across the band (Spearman median ≥ 0.89
between extremes, ≥ 0.97 for adjacent pairs). Exact top-20 set is less stable
(Jaccard median 0.19 for the 0.80↔1.00 extreme, 0.74 for adjacent). Reading:
global ranking robust; exact leaderboard shifts.

### Basis calibration (headline)

Spearman ρ between signed `modeled_congestion` and signed `basis`, per (ts,
derate) point, aggregated across 20 snapshots:

| Derate                           | ρ median  | ρ mean |
|----------------------------------|-----------|--------|
| **1.00 / 1.00**                  | **0.723** | 0.425  |
| 0.85 / 0.90                      | 0.392     | 0.405  |
| 0.80 / 0.85                      | 0.338     | 0.406  |
| 0.95 / 0.97                      | 0.336     | 0.299  |
| **0.90 / 0.95** (prior baseline) | **0.259** | 0.321  |

**1.00 / 1.00 wins decisively on median ρ (~3× the prior baseline).** Winner
robust to sample size (paired, ~6σ); middle-of-pack ordering (0.80/0.85/0.95)
is noisier and should not be over-interpreted. Mean–median gap at 1.00 (0.43
vs 0.72) indicates a low-ρ tail — probable West-Texas high-wind hours where
unmodeled export limits make the model directionally wrong regardless of
derate.

### Implications

- Production baseline moves to **1.00 / 1.00** — empirical, one fewer knob.
- Any full-year compute at 0.90 / 0.95 should be re-run at 1.00 / 1.00 before
  the Sprint-2 headline number is published: prior baseline is the *worst*
  of the five tested points on the metric the thesis rests on.
- Regime breakout is the next high-value add before writeup — the mean/median
  gap wants a story ("1.00 wins in load-driven regimes; wind-export hours
  are anticorrelated"). ~15 lines in the analysis script, no new solves.

## Notes

- **Single-snapshot solves.** Each iteration reloads
  `pypsa.Network(NETWORK_NC)` — bulk of wall-clock (solver itself <1 s). Batch
  by derate if this becomes annoying.
- **Load-shed backstop** (`SHED_COST=5000`, matches `compare_zonal_lmp`).
  Recorded `infeasible` = genuine topological failure, not marginal
  load-imbalance.
- **Failure granularity.** Adapter failure → whole ts skipped
  (`status='adapter_error'`). OPF infeasible at one derate → only that point
  is `infeasible`; other derates for the same ts still run.
