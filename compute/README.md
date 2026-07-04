# Compute

* `config.py`: config object that pulls from `/shared/settings.py`; kept to
  reduce changes during development.

* `constants.py`: carrers, regions, and `DEFAULT_P_MAX_PU` availability ceilings.

* `backfill_basis.py`: catch up script to populate `basis` value in
  `bus_snapshots` table.


## End-to-end run (full year)

The compute stack has four sequential layers. From a cold start (empty
database, fresh checkout), running the full flow means:

1. **OPF backfill** (`write_snapshots.py`) — the single OPF entry point.
   Per snapshot it persists `bus_snapshots` (per-bus LMP, modeled congestion,
   binding proximity, basis, dispatch) and `snapshot_meta` (system-λ
   estimates, load shed, hub LMPs, reference prices, dispatch-by-carrier,
   binding lines, top contingencies). Everything the analytical pipeline
   needs is written at solve time — no second file-based congestion path.
2. **Reference-price sanity checks** — re-confirm `hub k=200` and the
   `merit_order` λ choice on the larger sample.
3. **Dates file** — the list of timestamps the analytical pipeline will
   process.
4. **`run_pipeline.py`** — one command chains ERCOT → matrix → mapping
   (CM.1–CM.3) → clustering → scorecard end-to-end, reading its
   analytical inputs directly from `bus_snapshots` / `snapshot_meta`.

All commands assume `docker compose` from the repo root. Adjust
`--start` / `--end` and the run-id to your window.

### 1. Backfill OPF snapshots

`compute/write_snapshots.py` loops UTC hours in weekly chunks, solves the
DC-OPF batched through HiGHS, and upserts `bus_snapshots` + `snapshot_meta`
transactionally. It is the only place OPF is solved; every column downstream
consumers depend on lands here.

Full year (2025-01-01 → 2026-07-01, ~13,000 hours):

```
docker compose run --rm compute python /compute/write_snapshots.py \
    --start 2025-01-01 --end 2026-07-01 \
    --skip-existing
```

* `--skip-existing` — leaves already-`ok` rows alone; safe to resume after a
  crash. Mutually exclusive with `--force-recompute`.
* `--force-recompute` — overwrites existing rows via UPSERT, refilling new
  columns without a schema-version gate.
* `--chunk-size 6` (default) — hours per HiGHS PAMI batch. Do not increase
  without profiling; larger chunks blow up simplex pivots.
* Failures (infeasibility, missing weather/outage data) are recorded in
  `snapshot_meta` with `status != 'ok'` and the loop keeps going.

Progress lines report `rate=X/s ETA=Y min RSS=Z MB`. Expect ~1–2 hours of
walltime per compute-container per week of snapshots on stock hardware.

#### Parallelize across containers

Each solve is idempotent under `(interval_ts)`, so a full-year backfill fans
out across N containers by handing each a disjoint `--start`/`--end` slice.
`--skip-existing` covers any boundary overlap (two workers claiming the same
hour just no-op the second one). Suggested worker count: 4–6 per compute box
— each PyPSA solver + adapter holds ~1–2 GB resident.

```
# worker 1
docker compose run --rm compute python /compute/write_snapshots.py \
    --start 2025-01-01 --end 2025-04-01 --skip-existing
# worker 2
docker compose run --rm compute python /compute/write_snapshots.py \
    --start 2025-04-01 --end 2025-07-01 --skip-existing
# ...
```

### 2. Reference-price sanity checks

Two decisions bake into every downstream artifact: the k for the hub
k-nearest average, and the model-side λ method. Both were tuned on the
120-snapshot exploratory sample; re-run them against the full-year backfill
to confirm the choices still hold.

**External-λ range check** — verifies that the published ERCOT `dam_system_lambda`
distribution matches the plan hypothesis (60%+ hours in the $20–60 baseline,
scarcity-priced tails, occasional negatives). Doesn't touch model output:

```
docker compose run --rm compute python \
    -m compute.experiments.lambda_validation.dam_lambda_range
```

**Hub k-nearest sweep** — recomputes `hub_avg` for k ∈ {1,5,25,100,200,300,
500,1000,2000} from the persisted congestion column and reports
per-hub correlation / median-ratio / negative-count vs. ERCOT DAM SPP.
Requires an existing model run (`--model-results` and `--ercot-results`;
defaults point at v1-120-postfix):

```
docker compose run --rm compute python \
    -m compute.experiments.hub_k_sweep.sweep \
    --model-results /compute/runs/<run_id>/congestion/model_results.json.gz \
    --ercot-results /compute/runs/<run_id>/congestion/ercot_results.json.gz \
    --out /compute/experiments/hub_k_sweep/hub_k_sweep.md
```

If either sweep flags a shift (HB_NORTH max spiking, HB_WEST going majority-
negative, or `merit_order`/`system_lambda` correlation collapsing), update
`HUB_K_NEAREST` in `compute.congestion.metrics` and rerun the backfill before
serving. On the current codebase (`k=200`, `merit_order` fixed), the expected
outcome is: no change.

**Cross-method λ comparison** — side-by-side of all methods vs. NP4-523-CD
on the model window. Useful for a full-year confirmation that `merit_order`
still tracks published λ:

```
docker compose run --rm compute python \
    -m compute.experiments.lambda_validation.cross_method_compare \
    --model-results /compute/runs/<run_id>/congestion/model_results.json.gz \
    --ercot-results /compute/runs/<run_id>/congestion/ercot_results.json.gz
```

### 3. Build a dates file

`run_pipeline.py` consumes a JSON list (or `{regime: [iso]}` dict) of UTC
timestamps. For a regime-balanced sample:

```
docker compose run --rm compute python \
    -m compute.sample_specs.extract_dates --per-regime 30
```

That produces `reference_dates_120.json` (4 regimes × 30). For a full-year
run, either bump `--per-regime` or generate a flat all-hours file from
`snapshot_meta` (SELECT interval_ts WHERE status='ok'), and point
`--dates-file` at it in the next step.

### 4. Run the analytical pipeline

`compute/run_pipeline.py` chains the post-OPF stages under one `--run-id`:

    ERCOT → matrix
        → correlation_map → basis_regression → cca   (CM.1–CM.3 mapping)
        → clustering                                  (β-loading sweep)
        → scorecard                                   (per-zone headline)

Model-side congestion / hub LMPs / reference prices / dispatch are already
persisted by `write_snapshots.py` above; the pipeline reads them straight
from `bus_snapshots` / `snapshot_meta` rather than from a per-record JSON.

It writes provenance to `compute/runs/<run_id>/meta.json`, copies the dates
file into the run dir, and pre-flights that every timestamp has a
`bus_snapshots` row (exits non-zero with a suggested `write_snapshots.py`
command on gaps).

Full-year invocation:

```
docker compose run --rm compute python -m compute.run_pipeline \
    --run-id v1-fy26 \
    --dates-file /compute/sample_specs/reference_dates_full_year.json
```

Common flags:

* `--ref-methods hub_avg,system_lambda_merit_order,...` — subset of
  reference-price methods forwarded to the matrix stage. Clustering itself
  no longer sweeps refs (CM.6 froze it on `system_lambda_merit_order`).
* `--algos hierarchical_on_beta,hybrid_geo` — clustering algorithms.
  Default is `hierarchical_on_beta` (β-loadings from CM.2). `hybrid_geo`
  is the geographic/behavioral fallback.
* `--ks 4,6,8,10,12,16` — cluster counts to sweep.
* `--scorecard-algo hierarchical_on_beta` / `--scorecard-k 6` — which
  `(algo, K)` cell the scorecard aggregates over. Must be present in the
  sweep grid (`--algos` × `--ks`). Defaults are the CM.6 primary.
* `--skip-completed` (default) / `--no-skip-completed` / `--force` — control
  reuse of prior stage outputs under the same `--run-id`.

Artifacts land under `compute/runs/<run_id>/` with stage subdirs
(`congestion/`, `matrix/`, `mapping/`, `clustering/`). See
[`compute/runs/README.md`](runs/README.md) for the per-run layout.

The mapping and scorecard outputs — `mapping_correlation_<run_id>.npz`,
`mapping_basis_<run_id>.npz`, `mapping_cca_<run_id>.json`,
`scorecard_<run_id>.json`, `scorecard_series_<run_id>.npz` — are the Sprint
5 acceptance artifacts (correlation map, per-SP basis R², CCA scalar,
per-zone scorecard, per-hour `model_Z`/`ercot_Z`).

### 5. Pick the presentation partition (optional)

The clustering step sweeps `(algo, K)`; the scorecard runs against one
default cell (`hierarchical_on_beta`, K=6) so the pipeline can complete
autonomously. To eyeball the ranked alternatives and pick a different cell
for the frontend to display, use `select_zones.py` after the pipeline
finishes:

```
docker compose run --rm compute python \
    -m compute.clustering.select_zones \
    --summary /compute/runs/v1-fy26/clustering/clustering_summary_congestion_matrices.json
```

Then rerun the scorecard alone for the chosen cell:

```
docker compose run --rm compute python \
    -m compute.mapping.scorecard --run-id v1-fy26 \
    --algo <chosen_algo> --k <chosen_k>
```

Or re-invoke `run_pipeline.py` with `--scorecard-algo` / `--scorecard-k`
set to the chosen cell and `--skip-completed` (default) — every prior stage
is a no-op and only the scorecard reruns.


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

Each stage script is also runnable directly for ad-hoc use. All accept
`--run-id` (default paths resolve under `compute/runs/<run_id>/<stage>/`).

* **Model congestion / hub LMPs / reference prices / dispatch** — persisted
  by `write_snapshots.py`; there is no separate model-side congestion runner.
  To recompute a single hour, run:
  ```
  python /compute/write_snapshots.py \
      --start 2025-08-19T19 --end 2025-08-19T19 --force-recompute
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

* **Correlation map (CM.1)** —
  ```
  python -m compute.mapping.correlation_map --run-id debug-11
  ```

* **Basis regression (CM.2)** —
  ```
  python -m compute.mapping.basis_regression --run-id debug-11
  ```

* **CCA scalar (CM.3)** —
  ```
  python -m compute.mapping.cca --run-id debug-11
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

* **Scorecard** —
  ```
  python -m compute.mapping.scorecard --run-id debug-11 \
      --algo hierarchical_on_beta --k 6
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
