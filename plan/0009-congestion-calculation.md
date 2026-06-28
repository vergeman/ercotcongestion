# 0009 - congestion-calculation

Type: feat
Branch: feat/0009-congestion-calculation

## Goal

* Implement `compute_congestion()` helper in `/compute/experiments/congestion_calculation/congestion.py` that computes bus-level congestion as `LMP[bus] − reference_price[t]` under five reference choices: `hub_avg`, `custom_hub_avg`, `load_weighted`, `system_lambda`, `simple_mean`. Each method is computed in its own try block — one failure → NaN column, others unaffected.
* Build `/compute/experiments/congestion_calculation/congestion_snapshot.py` mirroring `reference_snapshot.py` — iterates `reference_dates.json`, runs OPF via `run_snapshot_for_ts`, builds the helper's inputs from model output, computes congestion, writes JSON.

## Context

* Phase 2 of the working outline: congestion is computed as `SPP[i,t] − reference[t]`; multiple reference choices are evaluated for spatial coherence.
* `fragility.py` + `snapshot.py` establish the helper + snapshot pattern to follow.
* `reference_snapshot.py` shows how to load dates, run OPF, and persist output; runner should mirror this structure.
* `reference_dates.json` at `/compute/profiling/reference_dates.json` is the date source; runner symlinks or imports from there.

## Approach

* Work in: `/compute/experiments/congestion_calculation/`
* New files: `congestion.py` (helper), `congestion_snapshot.py` (runner)
* `congestion.py`:
  * `compute_congestion(lmps, hub_lmps=None, loads=None, system_lambda=None) -> pd.DataFrame` — index = bus, columns = the five methods.
  * `hub_avg`: `lmps − hub_lmps[HB_BUSAVG]`
  * `custom_hub_avg`: `lmps − mean(HB_HOUSTON, HB_NORTH, HB_SOUTH, HB_WEST)`
  * `load_weighted`: `lmps − Σ(lmps × loads) / Σ(loads)`
  * `system_lambda`: `lmps − system_lambda` (model-side proxy passed in by runner)
  * `simple_mean`: `lmps − lmps.mean()`
  * Each method wrapped in its own try/except — failures yield a NaN column and a warning, never propagate.
* `congestion_snapshot.py`:
  * Mirror structure of `reference_snapshot.py` (same imports, same `sys.path`, same date-loading loop).
  * After `run_snapshot_for_ts`, build helper inputs from model state:
    * `hub_lmps`: LMP at synthetic bus nearest each ERCOT hub centroid (`/data/processed/hubs_lz_centroids.csv`). HB_BUSAVG also mapped to its centroid so it stays distinct from `load_weighted` and `simple_mean`.
    * `loads`: per-bus load from `n.loads.groupby('bus')['p_set'].sum()`.
    * `system_lambda`: `lmps.median()` — robust model-side proxy for the energy component (real-side analog: ERCOT NP6-322-CD).
  * Each input-build step and the OPF call wrapped in try/except so one bad timestamp or one missing input does not abort the run; failures are recorded in the JSON.
  * Output per timestamp: `{regime, ts, status, hub_lmps, system_lambda_proxy, lmp_summary, stats[method], congestion[method]}`.
  * Write to `congestion_results_{run_id}.json` in the same directory; `--run-id` defaults to `"baseline"`.
* Do NOT touch: `snapshot.py`, `fragility.py`, `reference_snapshot.py`, or any files outside `/compute/experiments/congestion_calculation/`.

## Acceptance

* [ ] `congestion.py` exports `compute_congestion()` with the five reference methods.
* [ ] `congestion_snapshot.py` runs without error via `docker compose run --rm compute python /compute/experiments/congestion_calculation/congestion_snapshot.py`.
* [ ] Output JSON contains one entry per (regime, timestamp) with congestion values keyed by method name; missing inputs (e.g. unknown hub) leave that method NaN without aborting others.
* [ ] Each method's bus values are centered near zero (mean ≈ 0 for simple_mean / load_weighted; near 0 for the hub-anchored references).
