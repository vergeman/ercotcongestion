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
* `--algos hierarchical_corr,kmeans_vec,pca_kmeans` — clustering algorithms.
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
      --coords-model /data/coords/model_bus_coords.csv \
      --coords-ercot /data/processed/settlement_points_geocoded.csv
  # or explicit paths:
  python -m compute.clustering.runner \
      --matrices compute/runs/debug-11/matrix/congestion_matrices.npz \
      --out-dir compute/runs/debug-11/clustering \
      --coords-model ... --coords-ercot ...
  ```


## Overview

| Quantity                    | Source                                | Measures                                             |
|:----------------------------|:--------------------------------------|:-----------------------------------------------------|
| **LMP**                     | OPF duals (per-bus power balance)     | Current clearing price                               |
| **Shadow Price** $\mu_\ell$ | OPF duals (per-line thermal limit)    | Severity of current congestion on line $\ell$        |
| **PTDF**                    | Topology                              | Sensitivity of line flows to bus injections (static) |
| **LODF**                    | Topology                              | Redistribution of flow when a line trips (static)    |
| **Fragility**               | PTDF + LODF + flows + contingency set | LMP dispersion caused by N-1                         |
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

* Fragility PTDF + LODF + N-1:
  * PTDF: Power Transfer Distribution Factor: L X B (line by bus) matrix
    * inject 1 mW at bus b, what fraction flows through line l
    * pure topology; computed once per network
  * LODF: Line Outage Distribution Factor: L x L matrix
    * LODF l,k: if line k trips,what fraction of k's flow ends up on line l
    * derived from PTDF + topology
    * also pure topology/structure
  * Contingency Loop: For each line outage k, in top-K (fragility) use LODF and
    compute new flows on every other line.
    * avoid re-solving the OPF.
  * Map to buses: If contingency k shows fragility; map back to buses by
    aggregating all top K lines to bus to get single fragility number.

* Model LMP vs Fragility
  * both outputs of OPF, share root cause, transmission congestion
  * LMP:
    * in uncongested network, system cost goes up by marginal generator cost
      (default max)
    * on transmission bind, buses now served by more expensive local
      generation - LMP rises
    * importing side buses have surplus cheap generation; LMP falls zero even
      negative.
  * Fragility: how much do LMP's disperse if a line tripped
    * ask OPF to solve each N-1, and see price variation at bus - fragile if bus
      has substantial price variation.
      * Fragility can be non-zero when LMPs are flat - network that is
        precarious, close to congestion. Ideal scenario to monitor, as prices
        could rise substantially and fan out.

* To Basis:
  * measures how "wrong" the model is
  * fragility: bus is structurally exposed to congestion-drive price variance
  * basis: real-world price diverged from the zonal benchmark
  * correlations - does fragility predict basis?
    * do fragile buses also price differently (basis) from zonal hub?
  * so now does basis capture spatial difference? A calibration or level error?
    etc.

* From OPF:
  * LMP: what are prices today
  * Fragility: how do prices respond to stress
  * Basis: how right/wrong is answer

* Shadow Prices: Lines
