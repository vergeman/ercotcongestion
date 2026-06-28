# 0010 - batch-pypsa

Type: refactor
Branch: feat/0010-batch-pyspa

## Goal

* Add `compute_snapshot_batch(n, ts_list, op_by_ts)` returning `dict[ts, result]` with same per-ts schema as current `compute_snapshot`.
* Build `create_model()` once per chunk (default chunk = 168, hourly snapshots = 1 week) instead of chunk per timestamp.
* Singificantly cut batched runs wall-clock time.

## Context

* Profiling shows `create_model()` is ~15s, 83% in `find_cycles` (KVL build); topology is static across all hours, so 8759 of those rebuilds are wasted.
* LP has zero inter-temporal coupling (no storage, ramps, UC, multi-invest) — snapshots are mathematically independent, batched results bit-identical to per-hour.
* Real outage data is generator-level via `p_max_pu` (time-varying, topology-invariant); line outages are stub-only with no data feed.
* Weekly chunk (168 snapshots) estimated ~4–8 GB peak with HiGHS simplex; annual all-at-once not feasible on commodity hardware.

## Approach

* All work and files should be done in: `/compute`
* Changes should focus particularly on `snapshot.py`; make sure `test_snapshot.py` and `write_snapshots.py` also handle batching
* any additional standalone callers in `experiments/` and `profiling/` should also have necessary changes.
* Entry point: new `compute_snapshot_batch` in `snapshot.py`; driver changes in `congestion_snapshot.py::main` to group timestamps into weekly buckets.
* Load network, apply static mutations (derates, `p_nom_extendable=False`, `r=1e-4` patch), add load-shed generators, and compute PTDF/LODF ONCE per process — not per timestamp or per chunk.
* Per chunk: call `n.set_snapshots(ts_list)`, stack `adapter.build(ts)` outputs into `n.loads_t.p_set` and `n.generators_t.p_max_pu` DataFrames, then `create_model()` + `solve()` + `assign_solution()` + `assign_duals()` once. Apply `marginal_price` weightings rescale vectorized over the full DataFrame.
* Per timestamp (post-solve, pure Python): slice `n.buses_t.marginal_price.loc[ts]`, `n.generators_t.p.loc[ts]`, `n.lines_t.p0.loc[ts]`, `n.lines_t.mu_upper/lower.loc[ts]`; pass to refactored `compute_fragility_at(dispatch, ptdf, bus_names)` and `compute_contingencies_at(flows, line_limits, lodf_lines, k)`.
* Size load-shed `p_nom` to max hourly total load across the chunk so every chunk is feasible; drop or demote `force_global_load_sf` retry to outer fallback.
* Do NOT touch: `operating_data_adapter.py` internals, `fragility.py` / `contingency.py` / `ptdf_lodf.py` math — only refactor function signatures to accept per-hour series directly.
* Do NOT introduce storage, ramps, or UC — would break the independence assumption that makes batching safe.

## Acceptance

* [ ] One weekly chunk (168 snapshots) builds in <30s and solves in <60s on dev box.
* [ ] Per-hour result dict for any `ts` matches current per-hour `compute_snapshot` within 1e-6 on LMPs, dispatch, and flows; verified on 5 sample timestamps from `profiling/reference_dates.json`.
* [ ] `congestion_snapshot.py --run-id batch-test` produces JSON with same record schema as `baseline`.
* [ ] `compute_fragility` and `compute_contingencies` outputs match reference run on the 5 sample timestamps.
