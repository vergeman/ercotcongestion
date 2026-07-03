# Compute

* `config.py`: config object that pulls from `/shared/settings.py`; kept to
  reduce changes during development.

* `constants.py`: carrers, regions, and `DEFAULT_P_MAX_PU` availability ceilings.

* `backfill_basis.py`: catch up script to populate `basis` value in
  `bus_snapshots` table.


## Running the pipeline

`compute/run_pipeline.py` is the canonical entry point. It chains the four
stages — model congestion → ERCOT congestion → matrix build → zonal clustering
sweep — under a single `--run-id`, writes provenance to
`compute/runs/<run_id>/meta.json`, and copies the dates file it consumed into
the run directory.

```
python -m compute.run_pipeline \
    --run-id v1-120 \
    --dates-file compute/sample_specs/reference_dates_120.json
```

Common flags:

* `--ref-methods hub_avg,system_lambda_kkt,...` — subset of reference-price methods.
* `--algos hierarchical_on_beta,hybrid_geo,hierarchical_corr` — clustering algorithms.
* `--ks 4,6,8,10,12,16` — cluster counts to sweep.
* `--records-output {gz,json,none}` — per-record congestion JSON output
  (default `gz`; `none` deletes the per-record files after the matrix stage
  exits `ok`).
* `--skip-completed` (default) / `--no-skip-completed` / `--force` — control
  reuse of prior stage outputs under the same `--run-id`.

Before launching congestion the orchestrator asserts every timestamp in the
dates file has a corresponding `bus_snapshots` row in Postgres; on gaps it
prints the missing timestamps and the suggested `write_snapshots.py --start
--end` command and exits non-zero without running the pipeline.

Artifacts land under `compute/runs/<run_id>/` with stage subdirs
(`congestion/`, `matrix/`, `clustering/`). See
[`compute/runs/README.md`](runs/README.md) for the per-run layout.


## Browsing derived-zone GeoJSONs

The clustering sweep emits one `zones_<ref>_<algo>_k<K>.geojson` per candidate
partition — >100 files for a full sweep. Two utilities help pick one.

`select_zones.py` prints a ranked table over the sweep summary; higher score =
more stable across time folds, better separated in feature space, and
geographically tighter. Does not auto-pick.

```
docker compose run --rm compute python -m compute.clustering.select_zones \
    --summary /compute/runs/v1-120/clustering/clustering_summary_congestion_matrices.json
```

`browse_zones.py` renders every candidate GeoJSON as a toggleable Folium
overlay in a single HTML file, colored by `cluster_id`. Pair with
`select_zones.py` to eyeball the top-ranked options.

```
docker compose run --rm compute python -m compute.clustering.browse_zones \
    --run-dir /compute/runs/v1-120 \
    --output /compute/runs/v1-120/clustering/clusters.html
```

Common flags:

* `--pattern "zones_*_hybrid_geo_k*.geojson"` — narrow the sweep (e.g. only
  geo-biased variants, or only `--pattern "zones_*_k10.geojson"` for K=10 across
  everything). Default: all `zones_*.geojson`.
* `--output clusters.html` — HTML destination. Default: `clusters.html` in cwd
  (write it under the run dir so it lands on the host bind mount).

Layers start hidden — flip one on at a time via the layer-control panel on
the right.


## Debugging individual stages

Each stage script is also runnable directly for ad-hoc use. All four accept
`--run-id` (default paths resolve under `compute/runs/<run_id>/<stage>/`) as
well as explicit-path flags for one-off invocations.

* **Model congestion** —
  ```
  python -m compute.congestion.snapshot_runner \
      --run-id debug-11 \
      --dates-file compute/sample_specs/reference_dates.json
  # or explicit output:
  python -m compute.congestion.snapshot_runner \
      --dates-file compute/sample_specs/reference_dates.json \
      --output /tmp/model_results.json.gz
  ```

* **ERCOT congestion** —
  ```
  python -m compute.congestion.ercot_runner \
      --run-id debug-11 \
      --dates-file compute/sample_specs/reference_dates.json
  ```

* **Matrix build** —
  ```
  python -m compute.matrix --run-id debug-11
  # or explicit input:
  python -m compute.matrix --model-results compute/runs/debug-11/congestion/model_results.json.gz
  ```

* **Clustering sweep** —
  ```
  python -m compute.clustering.runner \
      --run-id debug-11 \
      --coords-model /data/coords/model_bus_coords.csv
  # or explicit paths:
  python -m compute.clustering.runner \
      --matrices compute/runs/debug-11/matrix/congestion_matrices.npz \
      --out-dir compute/runs/debug-11/clustering \
      --coords-model ...
  ```


## Overview

| Quantity                    | Source                                | Measures                                             |
|:----------------------------|:--------------------------------------|:-----------------------------------------------------|
| **LMP**                     | OPF duals (per-bus power balance)     | Current clearing price                               |
| **Shadow Price** $\mu_\ell$ | OPF duals (per-line thermal limit)    | Severity of current congestion on line $\ell$        |
| **PTDF**                    | Topology                              | Sensitivity of line flows to bus injections (static) |
| **LODF**                    | Topology                              | Redistribution of flow when a line trips (static)    |
| **Modeled congestion**      | PTDF · signed shadow price            | Signed congestion contribution at each bus ($/MWh)   |
| **Binding proximity**       | \|flow\| / thermal limit, PTDF-weighted | How close each bus's driven lines are to binding   |
| **Basis**                   | Stored LMP − ERCOT zonal LMP          | Model error vs. reality                              |



### LMP from OPF

* LMP as dual variable (Lagrane Multiplier) of nodal power balance constraint at
  each bus's
  * if added 1 MW of demand at this bus, how much would total system cost go up?
  * `LMP b​ = ∂(total cost) / ∂(load at bus b) `

* PyPSA's DC-OPF
  * primal variables: generator dispatch, line flows
  * dual variables (one per constraint) - "duals" - per-bus power balance
    equations are the LMPs: `n.buses_t.marginal_price`
  * textbook definition: LMP = energy + congestion + losses - uses PTDF as
    "interpretation"
    * Energy: system price
    * Congestion: sum of line l across buses: PTDF l,b * μℓ (shadow price on line l)
    * Losses: 0 in DC-OPF
  * Attribute LMP to PTDF, but they come from LP (linear program - the
    optimization problem solved by OPF) duals.

* Structural inputs — PTDF + LODF:
  * PTDF: Power Transfer Distribution Factor: L X B (line by bus) matrix
    * inject 1 mW at bus b, what fraction flows through line l
    * pure topology; computed once per network
    * PyPSA convention: `PTDF[ℓ, b] > 0` means "injection at b raises flow on ℓ
      in ℓ's from→to direction"
  * LODF: Line Outage Distribution Factor: L x L matrix
    * LODF l,k: if line k trips,what fraction of k's flow ends up on line l
    * derived from PTDF + topology
    * also pure topology/structure

### Modeled congestion — signed per-bus congestion contribution

`modeled_congestion[b] = Σ_ℓ PTDF[ℓ, b] · μ_signed[ℓ]` in $/MWh, where
`μ_signed = mu_lower − mu_upper` (verified empirically on the DFW summer-peak
snapshot `2025-08-19T19:00`; see `docs/sample-recompute-gate-results.md`).

- Signed, not squared. Sum across lines, preserve sign.
- Positive: bus is on the import (higher-price) side of the binding constraint.
- Negative: bus is on the export (lower-price) side.
- Uncongested → 0 on every bus (all `μ = 0`).
- Islanded buses (absent from PTDF columns) carry NaN.

### Binding proximity — bus-level distance to binding

`binding_proximity[b] = max_ℓ |PTDF[ℓ, b]| · |flow_ℓ| / (s_nom_ℓ · s_max_pu_ℓ)`.

- Bus-aggregated max over lines the bus drives.
- Values in [0, ~1+]. May exceed 1 slightly on numerically-binding lines
  (solver tolerance).
- Reads "the worst line this bus can drive, weighted by how much it drives it".
- Only radial buses (|PTDF|=1) can reach 1.0; meshed buses share flow across
  multiple lines and typically peak in the 0.5–0.9 range even on
  heavily-congested hours.

### Modeled LMP vs modeled congestion

Both are OPF outputs sharing the transmission-congestion root cause:
- LMP: in an uncongested network, LMP ≈ marginal generator cost. On binding,
  import-side buses take more expensive local generation → LMP rises; export
  side has surplus cheap generation → LMP falls, can go negative.
- Modeled congestion: signed decomposition of the congestion term of LMP
  attributable to each binding line's dual. When LMPs are flat, mc ≈ 0.

### To Basis

- Basis measures how "wrong" the model is (stored LMP − ERCOT zonal LMP).
- Modeled congestion: which buses the model thinks are on the expensive side
  of a binding constraint.
- Binding proximity: which buses are structurally close to driving a bind.
- Correlations: do buses with high modeled congestion or high binding
  proximity also carry systematic basis? Signals topology drift vs. calibration
  drift.

### From OPF

- LMP: what are prices today
- Modeled congestion: which line-shadow contributions drive each bus's LMP today
- Binding proximity: which buses are structurally close to driving a bind
- Basis: how right/wrong the answer is vs. ERCOT truth

* Shadow Prices: Lines
