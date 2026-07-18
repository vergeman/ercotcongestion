# compute/runs/

Canonical artifact tree for pipeline outputs. One subdirectory per `run_id`. The
directory itself is gitignored (only this README is tracked) — runs are local
working state, not source.

Each run owns a self-contained set of artifacts keyed by `<run_id>`, with stage
subdirs that mirror the source package names (`congestion`, `matrix`,
`clustering`). A run produced by the orchestrator (`compute/run_pipeline.py`)
also carries `meta.json` (provenance: git sha, dates-file SHA-256, per-stage
status + elapsed) and a copy of the dates file it consumed.

```
compute/runs/<run_id>/
  meta.json                       # orchestrator provenance
                                  # (run_id, created_at, dates-file SHA-256, git sha, per-stage status/elapsed_s)

  reference_dates.json            # copy of the dates file used (provenance)
  <stage>.log                     # captured stdout+stderr, one per stage
  congestion/
    model_results.json            # was: congestion_results_<name>.json
    ercot_results.json            # was: ercot_congestion_results_<name>.json
  matrix/
    congestion_matrices.npz       # was: congestion_matrices_<name>.npz
    matrix_summary.json           # was: congestion_matrix_<name>.json
  mapping/
    mapping_correlation_<run_id>.npz            # CM.1 — sp_id → best_bus + top-k
    mapping_correlation_summary_<run_id>.json
    mapping_basis_<run_id>.npz                  # CM.2 — β-loadings + R² per SP/bus
    mapping_basis_summary_<run_id>.json
    mapping_cca_<run_id>.json                   # CM.3 — canonical correlations
    scorecard_<run_id>.json                     # CM.7 — per-zone headline
    scorecard_series_<run_id>.npz               # per-hour model_Z / ercot_Z
  clustering/
    summary.json
    cluster_labels_<ref>_<algo>_k<K>.npz        # bus_id → cluster_id (per sweep row)
    zones_<ref>_<algo>_k<K>.geojson             # optional cluster polygons
  ibp/
    bp_ercot.npz                                # bp_ercot[hour, sp] + hours/settlement_points/params
    diagnostics_YYYYMMDD.json                   # one per refit boundary: R², kept/dropped constraints, n_sf_clipped
```

## Sweep run_id naming

`compute.implied_binding_proximity.sweep_ibp` writes each grid point to a
`run_id` that encodes the fit hyperparameters, so a directory listing is
self-describing:

```
ibp_sweep_w{window}_r{refit}_l{lambda:g}_s{std_floor:g}_h{min_hours}
              │        │           │             │             └── --min-binding-hours: drop constraints binding fewer hours in the window
              │        │           │             └── --std-floor: lower bound on per-column std used for standardization
              │        │           └── --ridge-lambda: L2 penalty on the standardized ridge solve
              │        └── --refit-days: days between successive fits
              └── --window-days: rolling fit window
```

Example: `ibp_sweep_w60_r7_l0.001_s50_h100` is a 60-day window, weekly
refit, λ=1e-3, std_floor=50, min_binding_hours=100. Older sweep dirs may
omit the `_s.._h..` suffix — those predate the std_floor/min_hours grid
and used the fit.py defaults for those knobs.

**Calibrated production combo:** `ibp_sweep_w60_r7_l0.1_s100_h25`
(window=60, refit=7, λ=1e-1, std_floor=100, min_binding_hours=25). These
are the values `fit.py` bakes in as defaults and what the runner produces
when you don't override any knob. Ingest / promote this run_id (or one
produced with the same knobs under a friendlier `run_id`) when serving to
the API.

See `compute/implied_binding_proximity/README.md` for what each knob means
and the "Trial findings" table for how these values were chosen.

## Which run reaches the API / frontend

The API is DB-sourced — it no longer reads run artifacts off a served
symlink. Congestion (`/ercot_state_range`) and SPP (`/ercot_spp_range`)
are computed from the `ercot_dam_spp` / `dam_system_lambda` tables at
request time, and the `/map/*` endpoints resolve the served SF run per
request via `sf_window_meta`. The `runs/current` top-level symlink and the
`compute.promote` per-cell selection plane are retired (removed in
0094-0003).

## Served summary files

Two `mapping/` JSONs carry the headline numbers that reach the API and
frontend. They answer different questions — see the row-level notes.

### `mapping_correlation_summary_<run_id>.json` — per-SP mapping quality

Written by `compute/mapping/correlation_map.py`. For each ERCOT SP, its
Pearson-best model bus is picked; the file summarizes that distribution
across the ~964 SPs.

| Field | Meaning |
|---|---|
| `model_ref` / `ercot_ref` | Which columns of `congestion_matrices.npz` were used (e.g. `kkt_perbus` × `zone_local_spp`). |
| `n_sp` / `n_bus` | Rectangle size after variance prefilter. |
| `median_corr` | Median across SPs of Pearson corr(SP, best-bus) over hours. Typical strong pair ≈ 0.32. |
| `median_spearman` | Same, but Spearman rank correlation over hours. Outlier-robust; typically higher than `median_corr` on the same pair. |
| `median_sign` | Median fraction of hours where SP and best-bus have the same sign. 0.5 = random; 0.7+ = substantive directional agreement. |
| `pct_gt_0_5` / `pct_gt_0_7` | Fraction of SPs whose Pearson corr(best-bus) exceeds 0.5 / 0.7 — the "tail" of well-mapped SPs. |
| `pct_sign_gt_0_7` | Fraction of SPs whose sign-agreement with best-bus exceeds 0.7. |

Note: all `best_*` values are taken *at the Pearson-argmax bus*, not
re-argmaxed per metric.

### `scorecard_<cell>.json` — per-hour zone-aggregated fit

Written by `compute/mapping/scorecard.py` for a `(ref, algo, k)` cell.
Groups buses and SPs into clusters, aggregates congestion within each
cluster per hour, and scores model-side vs ERCOT-side agreement.

Headline (`headline` block):

| Field | Meaning |
|---|---|
| `zone_rank_spearman_per_hour` | Mean over hours of per-hour spatial Spearman across the derived-zone means. Measures *"do the zones line up hour by hour?"* Not comparable to `median_spearman` in the correlation summary. |
| `mean_corr` | Mean across zones of Pearson corr(model_Z, ercot_Z) over hours. Per-zone temporal fit, averaged. |
| `mean_sign_agreement` | Mean across zones of the fraction of hours where model_Z and ercot_Z have the same sign (with `$deadband` slack). |
| `n_hours` / `n_zones` | Rectangle behind the score (zones dropped by `min_members` are excluded). |

Per-zone rows (`zones` block) carry the same three metrics at zone
granularity plus `n_buses`, `n_sps`, `model_side_std`, `ercot_side_std`,
and outlier lists.

### Which one to look at

* *"How well does an individual SP track a specific bus?"* → correlation
  summary (`median_corr`, `median_spearman`, `median_sign`).
* *"Do the derived zones agree on when/where congestion happens?"* →
  scorecard headline (`zone_rank_spearman_per_hour`, `mean_corr`).
