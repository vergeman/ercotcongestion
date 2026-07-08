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

The API reads run artifacts off the `./compute:/compute` bind mount — no
ingestion. One selection plane, managed by `compute.promote`:

* Filesystem-served state — `runs/current` (top-level symlink) plus
  per-cell symlinks inside it (`mapping/scorecard.json`,
  `mapping/scorecard_series.npz`, `clustering/cluster_labels.npz`).
* DB-served state — `implied_binding_proximity_current[ercot]`.

Switching cells:

```
docker compose run --rm compute python -m compute.promote \
    --run-id <run-id> --ref <ref> --algo <algo> --k <k>
```

What each arg means:

| Arg | What it names | Example | Source of truth |
|---|---|---|---|
| `--run-id` | The pipeline run whose artifacts you want to serve. Names the subdir under `compute/runs/` and appears in per-run filenames (e.g. `mapping_correlation_<run_id>.npz`). Chosen at pipeline-launch time. | `v1-annual` | `compute/runs/<run_id>/` |
| `--ref` | Reference-price method used to build the model-side congestion matrix and the partition — see `compute/mapping/correlation_map.py`. Defines which `<ref>_model_C` slab in `congestion_matrices.npz` the scorecard aggregates over, and also the ERCOT-side matrix column `api/ercot_state.py` reads (they share the same ref axis under the promote-model). | `system_lambda_merit_order` | `DEFAULT_MODEL_REF` |
| `--algo` | Clustering algorithm used to partition buses. Sweep options live in `compute/clustering/`; the pipeline's `--algos` flag chooses which get built. | `hierarchical_on_beta` | `compute/clustering/runner.py` |
| `--k` | Cluster count for that algorithm — one of the `--ks` swept by the pipeline. | `6` | `compute/clustering/runner.py` |

Together `(ref, algo, k)` names a **cell** — one row in the clustering
sweep. Every run contains many cells on disk; promote picks one to
serve. The corresponding files must already exist under the run dir
(promote fails loudly otherwise); build them via the pipeline's
`--scorecard-ref` / `--scorecard-algo` / `--scorecard-k` flags or by
running `compute.mapping.scorecard` directly.

No API restart, no image rebuild, no configmap edit. The topology cache
invalidates automatically when the `cluster_labels.npz` symlink is
repointed. The frontend takes no build-time run parameter — `fetchScorecard()`
is arg-less and `/api/meta` exposes the currently-served identity on
request.
