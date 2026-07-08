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
   OPF is a prerequisite of `run_pipeline.py`, not a stage inside it, and
   can be parallelized across containers independently.
2. **Reference-price sanity checks** — re-confirm `hub k=200` and the
   `merit_order` λ choice on the larger sample.
3. **Dates file** — the list of timestamps the analytical pipeline will
   process.
4. **`run_pipeline.py`** — one command chains matrix → mapping (CM.1–CM.3)
   → clustering → scorecard end-to-end, reading its analytical inputs
   directly from `bus_snapshots` / `snapshot_meta`.

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
    -m compute.calibration.lambda_validation.dam_lambda_range
```

**Hub k-nearest sweep** — picks `k` for the model-side `hub_avg` reference
price. For each ERCOT hub `H`, model `hub_avg(k) = mean(LMP_b)` over the `k`
model buses nearest `H`'s geographic centroid; the comparator is the
published ERCOT DAM SPP for that same hub settlement point (one scalar per
hour, straight from `ercot_dam_spp` — not a k-average on the ERCOT side).
Sweeps k ∈ {1,5,25,100,200,300,500,1000,2000} by streaming per-bus LMPs
from `bus_snapshots`. Emits a recommended k on stdout and at the top of the
report — smallest k with no spike / no negative and drift ≤ 5%; falls back
to the lowest-drift k if none clears the gate:

```
docker compose run --rm compute python \
    -m compute.calibration.hub_k_sweep.sweep \
    --start 2025-01-01 --end 2025-12-01 \
    --out /compute/calibration/hub_k_sweep/hub_k_sweep.md
```

Per-hub table columns and what they tell us:

* `corr` — Pearson correlation of model `hub_avg(k)` against the ERCOT hub
  SPP over the window. Movement match: does the model's hub price track
  the published hub price hour-by-hour?
* `med_ratio` — median of `hub_avg(k) / ERCOT_hub_SPP`. Level bias:
  1.0 = matched central level, > 1 = model systematically overshoots,
  negative = model dips below zero on hours where ERCOT stays positive.
* `n_spike(|x|>500)` — hours where `|hub_avg(k)| > $500`. A single unstable
  bus in a small k-nearest set drags the mean into a spike; larger k damps
  this. Should be zero once the neighborhood is wide enough to average out
  solver artifacts.
* `n_neg` — hours where `hub_avg(k) < 0`. ERCOT hub SPPs are essentially
  always ≥ 0, so frequent negatives mean the k-nearest set picks up too
  many export-constrained (cheap-side) buses — the HB_WEST k=1 failure
  mode from 0049.

If the sweep flags a shift (HB_NORTH max spiking, HB_WEST going majority-
negative, or `merit_order`/`system_lambda` correlation collapsing), update
`HUB_K_NEAREST` in `compute.congestion.metrics` and rerun the backfill before
serving.

**Cross-method λ comparison** — side-by-side of all methods vs. NP4-523-CD
over the requested window, reading `snapshot_meta.reference_prices` and
`dam_system_lambda.system_lambda` directly. Useful for a full-year
confirmation that `merit_order` still tracks published λ:

```
docker compose run --rm compute python \
    -m compute.calibration.lambda_validation.cross_method_compare \
    --start 2025-01-01 --end 2025-12-01
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

    matrix
        → correlation_map → basis_regression → cca   (CM.1–CM.3 mapping)
        → clustering                                  (β-loading sweep)
        → scorecard                                   (per-zone headline)
        → promote                                     (opt-in — flip serving)

OPF is a prerequisite, not a stage: `write_snapshots.py` must have already
populated `bus_snapshots` / `snapshot_meta` for every timestamp in the
dates file. The pipeline reads those tables directly — there is no
per-record JSON path anymore, and no `--records-output` flag.

It writes provenance to `compute/runs/<run_id>/meta.json`, copies the dates
file into the run dir, and pre-flights that every timestamp has
`snapshot_meta.status='ok'` (exits non-zero with a suggested
`write_snapshots.py` command on gaps or failed solves).

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
* `--scorecard-ref system_lambda_merit_order` / `--scorecard-algo hierarchical_on_beta`
  / `--scorecard-k 6` — which `(ref, algo, K)` cell the scorecard aggregates
  over. Must be present in the sweep grid (`--ref-methods` × `--algos` × `--ks`).
  Defaults are the CM.6 primary. The scorecard writer emits per-cell filenames
  (`scorecard_<run_id>_<ref>_<algo>_k<K>.json`) so multiple cells for the
  same run coexist — `compute.promote` picks which one is served.
* `--promote` — after `scorecard`, run `compute.promote` to flip the
  `runs/current` symlink, the per-cell symlinks inside the run, and the
  IBP DB pointer at this run + the chosen scorecard cell. Idempotent
  (repeats are no-ops). Off by default so a rebuild doesn't silently
  switch what the API serves.
* `--skip-completed` (default) / `--no-skip-completed` / `--force` — control
  reuse of prior stage outputs under the same `--run-id`.

Artifacts land under `compute/runs/<run_id>/` with stage subdirs
(`matrix/`, `mapping/`, `clustering/`). See
[`compute/runs/README.md`](runs/README.md) for the per-run layout.

The mapping and scorecard outputs — `mapping_correlation_<run_id>.npz`,
`mapping_basis_<run_id>.npz`, `mapping_cca_<run_id>.json`,
`scorecard_<run_id>_<ref>_<algo>_k<K>.json`,
`scorecard_series_<run_id>_<ref>_<algo>_k<K>.npz` — are the Sprint 5
acceptance artifacts (correlation map, per-SP basis R², CCA scalar,
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
    --ref <chosen_ref> --algo <chosen_algo> --k <chosen_k>
```

Or re-invoke `run_pipeline.py` with `--scorecard-ref` / `--scorecard-algo`
/ `--scorecard-k` set to the chosen cell and `--skip-completed` (default) —
every prior stage is a no-op and only the scorecard (and, if requested,
promote) reruns.

To point the API at the newly-selected cell in the same call, add
`--promote`:

```
docker compose run --rm compute python -m compute.run_pipeline \
    --run-id v1-fy26 \
    --scorecard-ref system_lambda_merit_order \
    --scorecard-algo hierarchical_on_beta \
    --scorecard-k 8 \
    --promote
```

Or run `compute.promote` on its own after the fact (same flags, no
compute work — flips symlinks and DB pointer only):

```
docker compose run --rm compute python -m compute.promote \
    --run-id v1-fy26 \
    --ref system_lambda_merit_order \
    --algo hierarchical_on_beta \
    --k 8 \
    [--dry-run]
```


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

---

## How run outputs reach the API

`compute.run_pipeline` writes artifacts under `compute/runs/<run_id>/`. The API
reads those files directly — there is no ingestion step.

### Volume mount

`docker-compose.yml` mounts `./compute:/compute` on the `api` service, so
`compute/runs/<run_id>/` on the host appears at `/compute/runs/<run_id>/`
inside the container.

### Which run the API surfaces

`compute.promote` (see step 5 above) manages the entire selection surface:

* `runs/current` — a top-level symlink naming the served run.
* `runs/current/mapping/scorecard.json`,
  `runs/current/mapping/scorecard_series.npz`,
  `runs/current/clustering/cluster_labels.npz` — per-cell symlinks
  pointing at the promoted `(ref, algo, K)` cell.
* `implied_binding_proximity_current[ercot]` — the DB pointer for IBP
  rows, flipped in the same `compute.promote` call.

Two knobs in `shared/settings.py`:

| Env var | Default | Purpose |
|---|---|---|
| `SERVED_RUN_DIR` | `/compute/runs/current` | The only path the API opens; usually the top-level symlink |
| `COMPUTE_RUNS_DIR` | `/compute/runs` | Root of the runs tree — used by `compute.promote` on the compute pod |

### Consumers

| Endpoint / module | Reads |
|---|---|
| `api/services/topology_builder.py` | `<served>/clustering/cluster_labels.npz` (symlink); `<served>/mapping/mapping_correlation_<run>.npz`; `<served>/clustering/zones_<ref>_<algo>_k<K>.geojson`. Bus↔cluster join baked into `topology.json`; cache invalidated when the symlink's target or mtime changes. |
| `api/ercot_state.py` | `<served>/matrix/congestion_matrices.npz`. Ref key derived from `<served>/mapping/scorecard.json`'s `params.ref`, cached by mtime. |
| `api/validation.py` | `<served>/mapping/scorecard.json` + `scorecard_series.npz` (symlinks). No query params. |
| `api/meta.py` | `readlink(<served>)`, `<served>/mapping/scorecard.json`'s `params`, `implied_binding_proximity_current[ercot]`. |
| `api/state.py` | `snapshot_meta` + `bus_snapshots` in Postgres (unrelated to promote). |

Other run artifacts (`mapping_basis_*.npz`, `mapping_cca_*.json`, per-cell
scorecards not currently linked-to) are intermediate — consumed by later
compute stages or held on disk as historical cells.

### Switching the served run/cell

One idempotent CLI call, no API restart, no image rebuild, no configmap
edit:

```bash
docker compose run --rm compute python -m compute.promote \
    --run-id v1-annual \
    --ref system_lambda_merit_order \
    --algo hierarchical_on_beta \
    --k 6
```

The topology cache (`topology.json`) stamps a `(readlink target, mtime)`
key for `cluster_labels.npz` and rebuilds itself on the next request
whenever either shifts, so a promote-flip busts it automatically.

Inspecting what's live:

```bash
readlink /compute/runs/current                              # → v1-annual
readlink /compute/runs/current/mapping/scorecard.json       # → the served cell
psql -c "SELECT run_id, promoted_at FROM \
         implied_binding_proximity_current WHERE layer='ercot'"

curl http://localhost:8000/meta                             # same, as JSON
```

---

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

* **Matrix build** — reads model side directly from `bus_snapshots` +
  `snapshot_meta` and the ERCOT side directly from `ercot_dam_spp` +
  `dam_system_lambda` + `load_by_zone`, then writes
  `runs/<run_id>/matrix/congestion_matrices.npz`:
  ```
  python -m compute.matrix \
      --run-id debug-11 \
      --dates-file compute/sample_specs/reference_dates.json
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
      --ref system_lambda_merit_order \
      --algo hierarchical_on_beta --k 6
  ```

* **Promote** — no compute; just flips symlinks + the IBP DB pointer to
  make an already-built cell live for the API. Idempotent, safe to re-run.
  ```
  python -m compute.promote --run-id debug-11 \
      --ref system_lambda_merit_order \
      --algo hierarchical_on_beta --k 6 \
      [--dry-run]
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

#### Why the congestion matrix reads `modeled_congestion` directly (`kkt_perbus`)

Under DC-OPF the KKT identity says
`LMP_i = λ + Σ_ℓ PTDF[ℓ,i]·μ_signed_ℓ`, so
`LMP_i − Σ PTDF·μ = λ` is bus-independent at the optimum.
Two consequences the matrix pipeline hinges on:

1. `Σ PTDF · μ` = `LMP − λ_per_bus_KKT` up to numerical residual. It's
   the same "congestion component" whether you build it forward from
   the duals or backward from LMP minus the per-bus KKT residual.
2. `Σ PTDF · μ` lives in the common-mode-free subspace by construction:
   its bus-mean is ~0 per hour (empirically 13 std over `v1-annual`,
   vs 5 for ERCOT — small residual from bus-population asymmetry, not
   a bug).

Before 0071, model-side `model_C = LMP − system_lambda_merit_order`
subtracted the copper-plate (**uncongested**) λ from a **congested** LMP,
so the difference carried an extra scalar-per-hour term
`(λ_congested − λ_uncongested)` on every bus. On `v1-annual` that scalar
has `std ≈ 260, mean ≈ −117` (see plan 0071 Check B). No per-bus signal
survived correlation against ERCOT once that common-mode was riding in.

The `kkt_perbus` reference method skips the scalar subtraction entirely
and writes `model_C[b, t] = modeled_congestion[b, t]` straight from
`bus_snapshots`. `compute/matrix.py::build_model_matrices` recognizes
the name and widens its streaming query accordingly. On the ERCOT side,
`system_lambda` (SCED power-balance dual) remains the correct
congested-reference match — see the `correlation_map` invocation in
plan 0071 for the canonical pairing.

**What this fix does — and what it does not.** On `v1-annual-kkt`,
`kkt_perbus × system_lambda` lifts `correlation_map` median_corr from
0.232 → 0.297, matching the `load_weighted × load_weighted` proxy
(0.298). That is the algebraic common-mode leaving the model side.
It does **not** by itself dissolve the winner-concentration or lift
the p90/p99 tail (still 3 buses claim 42% of SPs, `pct>0.5` = 1%).
That residual is a zonal-level component that a system-wide reference
cannot cancel by construction; a per-load-zone reference is the natural
follow-up. See `plan/0071-kkt-perbus-congestion.md` for the full
comparison table.

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
