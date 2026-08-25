# compute/runs/

Canonical artifact tree for pipeline outputs. One subdirectory per `run_id`. The
directory itself is gitignored (only this README is tracked) — runs are local
working state, not source.

Each run owns a self-contained set of artifacts keyed by `<run_id>`. Artifact
directory names are a stable storage contract, not Python package paths: the
production libraries are `inputs`, `sf_map`, `mu_forecast`, `projection`, and
`evaluation`, while the `sf/`, `mu/`, and `forecast/` artifact directories
remain intentionally named for their stored model outputs. A run produced by
the orchestrator (`compute/run_pipeline.py`) also carries `meta.json`
(provenance: git sha, dates-file SHA-256, per-stage status + elapsed) and a
copy of the dates file it consumed.

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
  sf/                                           # SF-map artifacts (map run)
    diagnostics_YYYYMMDD.json                   # one per refit boundary: R², kept/dropped constraints, n_sf_clipped
    eval.csv                                     # honest out-of-window eval (compute.evaluation.sf)
  mu/                                           # μ-forecast artifacts (forecast run)
    mu_weekly.csv                               # mu_model --out: walk calibration metrics (brier/ece/mae_mu_*)
    mu_score_weekly.csv                         # compute.evaluation.mu: score currencies (source/regime/pooled_r2 …)
    mu_preds.npz                                # mu_model --preds-out: predictions / residual pool
    spill/                                      # on-disk bind-matrix / panel spill (transient)
  forecast/                                     # nodal-projection artifacts (forecast run)
    mu_bands_weekly.csv                         # backfill_nodal --out: P50 band metrics
    mu_nodal.npz                                # backfill_nodal --nodal-out: nodal P10/P50/P90 + point panel
```

> **`mu-all-v1` (forecast) vs `map-v1` (SF).** A forecast run and the SF map it
> projects through are versioned independently: the `sf/` subdir belongs to the
> map run (`map-v1`), while `mu/` + `forecast/` belong to the forecast run
> (`mu-all-v1`). `backfill_nodal --map-run-id` names the dependency. `mu_weekly.csv`
> and `mu_score_weekly.csv` are two different files with two different schemas — the
> former is `mu_model`'s calibration, the latter the scoreboard/r5 score input.

## Sweep run_id naming

`compute.experiments.sf.sweep` writes each grid point to a
`run_id` that encodes the fit hyperparameters, so a directory listing is
self-describing:

```
sf_sweep_w{window}_r{refit}_l{lambda:g}_s{std_floor:g}_h{min_hours}
              │        │           │             │             └── --min-binding-hours: drop constraints binding fewer hours in the window
              │        │           │             └── --std-floor: lower bound on per-column std used for standardization
              │        │           └── --ridge-lambda: L2 penalty on the standardized ridge solve
              │        └── --refit-days: days between successive fits
              └── --window-days: rolling fit window
```

Example: `sf_sweep_w60_r7_l0.001_s50_h100` is a 60-day window, weekly
refit, λ=1e-3, std_floor=50, min_binding_hours=100. Older sweep dirs may
omit the `_s.._h..` suffix — those predate the std_floor/min_hours grid
and used the then-current fit defaults for those knobs.

**Current production operating point:** window=240 days, refit=7 days,
λ=1, std_floor=100, and min_binding_hours=25. `compute.sf_map.config`
owns the shared defaults; the map and μ-forecast stages use them unless a
CLI explicitly overrides a knob. The older 60-day / λ=0.1 sweep remains a
historical experiment, not the serving default.

See `docs/legacy/implied_binding_proximity.md` for what each knob means
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
