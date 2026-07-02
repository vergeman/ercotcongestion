# Derate Sweep — Sprint 3

Sensitivity + calibration harness for the tied `(line_derate, tx_derate)` knob
inside the OPF. Runs on the Sprint-0 reference-hour sample; does not touch the
full-year recompute.

## Why this exists

Two derate constants — `line_derate=0.9`, `tx_derate=0.95` — are applied
multiplicatively to `s_nom` inside `apply_static_mutations`
(`compute/operating_conditions.py`). They shrink the feasible region of the
DC-OPF and change *which* constraints bind. That means:

- Derate is **not order-preserving.** "Set to 1.0 to simplify" is invalid by
  reasoning — you can't fold it out post-hoc. The only way to know if the
  spatial answer depends on the knob is to sweep it and look.
- Real ERCOT inputs produce binding lines at `derate=1.0` (an earlier
  zero-congestion result was the unloaded bare network, not the loaded one),
  so `1.0` is a legitimate baseline candidate — it has to be decided
  empirically, not by fiat.

The sweep is the empirical answer. Its job is to convert the derate from an
arbitrary hand-picked constant into either (a) a demonstrated-robust knob that
doesn't affect the spatial conclusion inside a band, or (b) a value calibrated
against the ground truth we care about (observed basis).

## What the sweep tests

Both scripts read the same Sprint-0 sample (~20 timestamps across summer peak,
high West-Texas wind, mild shoulder, winter peak — see
`compute/sample_specs/reference_dates.json`).

Three questions, in order:

1. **Feasibility band.** For each derate point, what fraction of the sample
   solves? Establishes the empirically feasible window and identifies the
   tightest derate that still clears every regime.

2. **Rank stability across the band.** Per snapshot, compare the top-K
   congested buses across every pair of derate points using Jaccard overlap on
   the top-K set and Spearman ρ on the full `|modeled_congestion|` rank
   vector. The intended story if the numbers cooperate: "the spatial ranking
   is stable across the feasible band; the derate value sets intensity, not
   location."

3. **Basis calibration.** Per (snapshot, derate) point, correlate signed
   `modeled_congestion` against signed observed `basis` (from the ERCOT zonal
   LMP tables). Aggregate across the sample. The derate with the highest
   median Spearman ρ vs basis is the empirically-calibrated production
   baseline. If `1.0` wins on ρ, we drop the knob — one fewer arbitrary
   constant in the model.

## Dependencies

- Sprint 1 (zonal load disaggregation) — already merged. The adapter is
  called with `force_global_load_sf=False`, so the sweep runs on Sprint-1
  corrected geography by default. Do **not** calibrate derate against basis
  on the wrong load geography — that tunes one error to compensate for
  another. This ordering constraint is why Sprint 3 waits on Sprint 1.
- Sprint 2 (metric reframe) — the sweep uses signed `modeled_congestion`, not
  the retired `fragility` blob. Sweeping the retired metric would compound
  the sign-loss and headroom-double-count issues Sprint 2 fixed.
- Sprint 0A snapshot sample — reused as-is; no new sample drawn.

## Files

- `derate_sweep.py` — harness. Iterates
  `sample × DERATE_AXIS`, solves each point single-snapshot, computes
  `modeled_congestion` / `binding_proximity` / `basis`, writes long-form CSVs.
- `derate_sweep_analysis.py` — consumes the two CSVs and prints the three
  reports above. No plots; text output first, plots later if the numbers are
  interesting enough to warrant them.
- `results/` — output directory (git-tracked; regenerated per run).
  - `snapshot_summary.csv` — one row per `(ts, line_derate, tx_derate)`:
    status, `n_binding_lines`, MC totals, basis stats, load-shed MW,
    solve time.
  - `bus_metrics.csv` — one row per `(ts, line_derate, tx_derate, bus)`:
    `modeled_congestion`, `binding_proximity`, `basis`. Long-form; feeds all
    downstream analysis.

## Derate axis

Tied `(line, tx)` so the search is 1-D rather than 5×5. Transformers stay
slightly looser than lines (they're protected differently in real systems).

```
(1.00, 1.00)   # unity baseline — the "drop the knob" candidate
(0.95, 0.97)   # mild derate
(0.90, 0.95)   # current production baseline
(0.85, 0.90)   # tight
(0.80, 0.85)   # near lower feasibility edge (0.70 is known infeasible at 86 GW)
```

Five points is enough to see whether ranking is stable and to identify the
best calibration point; a finer grid can be added later if the calibration
curve is flat and the winning region is ambiguous.

## Running

```
docker compose run --rm compute python /compute/derate_sweep/derate_sweep.py
docker compose run --rm compute python /compute/derate_sweep/derate_sweep_analysis.py
```

Both scripts accept `--sample` / `--out` / `--in` / `--top-k` overrides;
defaults are wired to this subdirectory.

## Notes / caveats

1. **Single-snapshot solves, not batched.** Each iteration reloads
   `pypsa.Network(NETWORK_NC)` from disk, which is the bulk of the wall-clock
   cost per point (the OPF itself solves in well under 1 s). Expect ~20–60
   minutes total for the full ~100-solve sweep (20 ts × 5 derate points).
   This is deliberate — the single-snapshot path is much easier to reason
   about than `compute_snapshot_batch`, and the sweep is a one-shot
   robustness exercise, not a production loop. If it turns out to be
   annoying, batching by derate (five snapshots per network, per derate) is
   the fix; but wait until timings actually justify it.

2. **Output size.** `bus_metrics.csv` is roughly
   `n_buses × n_ts × n_derates ≈ 2000 × 20 × 5 = 200k rows`, on the order of
   15–30 MB as CSV. Small enough to commit but big enough that you may want
   to gzip if you iterate the sweep multiple times.

3. **Load-shed backstop.** Each solve adds a per-bus `shed_` generator at
   `SHED_COST=5000` (matches the compare_zonal_lmp precedent), so
   infeasibility recorded in `status='infeasible'` is a genuine
   physical/topological failure rather than a marginal load-imbalance
   artifact.

4. **Feasibility fallback is at derate level, not adapter level.** If the
   *adapter* fails to build (e.g. the DB has no load row), that snapshot is
   skipped entirely with `status='adapter_error'`. If the adapter succeeds
   but the OPF is infeasible at a specific derate, only that (ts, derate)
   point is `infeasible`; other derates for the same ts still run.

5. **What the sweep is NOT.** It is not a full-year recompute, and it does
   not decide the production baseline on its own — the interview-defensible
   claim is a combined story: "here's the feasibility band, here's the
   ranking stability inside it, here's the derate that best matches basis on
   this sample." The final choice + written justification lands in the
   Sprint 3 writeup, not in this directory.
