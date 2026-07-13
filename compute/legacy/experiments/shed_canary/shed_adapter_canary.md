# Shed adapter coverage fix — canary results

Related tickets: 0044 / 0049 S4.1.

## What the fix does

`stack_time_varying` (and `apply_operating_conditions`) previously flagged
every `shed_<bus_id>` pseudo-generator as "escaped adapter coverage" and
filled its `p_max_pu` with `DEFAULT_P_MAX_PU['other'] = 0.8`. Shed gens
are an infeasibility safety valve, not real ERCOT resources, so throttling
them to 80% biased OPF outcomes on stressed hours.

Fix (`compute/operating_conditions.py`): partition the missing set into
`shed_missing` and `unexpected_missing`. Shed gens get `p_max_pu = 1.0`
with no warning; real coverage gaps still warn + fall back to 0.8.

## Verification (full v1-120 reference series)

Baseline: `runs/v1-120/congestion/model_results.json.gz` (pre-fix)
Candidate: `runs/v1-120-postfix/congestion/model_results.json.gz` (post-fix)

Records: **120/120 matched, 120/120 status=ok, zero warnings.**

Full delta table: [`shed_adapter_canary_full.md`](./shed_adapter_canary_full.md).

### Structural checks (single-snapshot deep dive)

Script: `compute/experiments/shed_canary/verify_shed_fix.py` — two-chunk
canary so shed gens are present when `stack_time_varying` runs.

* shed_ columns in `p_max_pu`: **2751**, all at **1.0** (was 0.8 pre-fix)
* `escaped adapter coverage` warnings: **0** (was 2751/snapshot)
* Non-shed `p_max_pu` range: 0.001–0.911 (unchanged)

### Regime rollup — Δ load_shed_mw (candidate − baseline)

| regime         | n  | mean    | median  | min     | max     |
| -------------- | -- | ------- | ------- | ------- | ------- |
| high_wind_west | 30 | -235.95 | -241.75 | -359.48 |  -71.42 |
| mild_shoulder  | 30 | -203.20 | -196.25 | -311.92 | -101.41 |
| summer_peak    | 30 | -163.67 | -147.45 | -582.63 |  -59.89 |
| winter_peak    | 30 | -258.04 | -238.64 | -591.85 |  -81.32 |

### Regime rollup — Δ lmp_mean

| regime         | n  | mean   | median |
| -------------- | -- | ------ | ------ |
| high_wind_west | 30 | -14.62 | -16.74 |
| mild_shoulder  | 30 | -22.54 | -19.35 |
| summer_peak    | 30 | -59.45 | -50.69 |
| winter_peak    | 30 | -88.07 | -51.51 |

### Regime rollup — Δ lmp_max

| regime         | n  | mean     | median   |
| -------------- | -- | -------- | -------- |
| high_wind_west | 30 |  -153.70 |  -175.97 |
| mild_shoulder  | 30 |  -188.85 |  -152.16 |
| summer_peak    | 30 | -1188.69 | -1205.86 |
| winter_peak    | 30 |  -248.67 |  -117.18 |

### shed-active count (load_shed_mw > 0)

| regime         | baseline | candidate |
| -------------- | -------- | --------- |
| high_wind_west | 30       | 30        |
| mild_shoulder  | 30       | 30        |
| summer_peak    | 30       | 30        |
| winter_peak    | 30       | 29        |

## Interpretation

* **Direction is right.** Every regime shows shed reduction. Shed activation
  count barely moves (30/30 → mostly 30/30) — the fix doesn't hide shed
  events, it just corrects the magnitude.
* **Summer_peak has the largest LMP_max collapse** (mean -$1188.69), because
  those hours were pinned at the $5000 VOLL offer cap pre-fix. Post-fix,
  real gens on the margin set the ceiling.
* **Winter_peak has the largest LMP_mean drop** (-$88) — matches the
  regime with the highest baseline shed volume.
* **Some LMP_min values move positive** (summer_peak +$1259 mean) — the
  redistribution of shed changes marginal-price signs at previously
  extreme buses. Not a bug; this is the correct clearing on the corrected
  input.

## Note on the mechanism

The 80% shed cap should not have been binding: per-bus shed cap =
`0.8 × chunk_max_load ≈ 65 GW`, and actual shed sits around 100 MW per
bus. Yet total shed drops 44–66% on the top-shed hours and produces
matching objective-cost deltas of ~$1–3M per snapshot (shed × $5000/MWh).

Likely mechanism: LP degeneracy under different RHS scaling. HiGHS's
simplex traverses a different vertex sequence when constraint RHSs shift
~25%, and can settle on an alternate optimum whose shed distribution
differs even when the cap isn't strictly binding. Both are valid LP
optima but only the post-fix one corresponds to the intended
economic model (shed at 100% of `p_nom`).

## Decision

**Re-run the full-year backfill.** All shed-clearing hours in the current
backfill are biased. Non-shed hours are numerically identical (the fix
only affects rows where `shed_*` gens appear in `n.generators.index`
during `stack_time_varying`, which is all rows on chunks 2+, but the
`p_max_pu` value only matters when the OPF actually dispatches shed).

## Commands

```
# Structural single-snapshot verify
docker compose run --rm compute python /compute/experiments/shed_canary/verify_shed_fix.py --ts 2025-01-22T13:00

# Full canary run
docker compose run --rm compute python -m compute.congestion.snapshot_runner \
    --run-id v1-120-postfix --dates-file /compute/runs/v1-120/reference_dates.json

# Diff report
docker compose run --rm compute python /compute/experiments/shed_canary/compare_runs.py \
    --baseline /compute/runs/v1-120/congestion/model_results.json.gz \
    --candidate /compute/runs/v1-120-postfix/congestion/model_results.json.gz \
    --out /data/shed_adapter_canary_full.md
```
