# 0081 persist-sf-matrix

Type: feat
Branch: feat/0081-persist-sf-matrix

## Goal

* Persist the per-refit `SF` matrix (constraint×SP) that `rolling_bp` currently computes and discards.
* Add `implied_shift_factors` (SF rows) + `sf_window_meta` (one row per refit) tables; leave `implied_binding_proximity` (scalar `bp`) untouched.
* Extend `sf/runner.py` so `--persist-sf` writes SF rows via the existing `on_refit_window` hook, sparsified below a `|SF|` threshold, keyed by `run_id`.

## Context

* Gap from §0.1: `rolling.py:108` fits `SF`, `metric.py` reduces it to `bp = max_c|SF[c,sp]|`, then `SF` is thrown away. Only the scalar survives (migration 22).
* Every v3 surface (node explorer, `congestion = −Σ SF·μ̂`, coverage decomp, grouping) needs the full matrix — this is foundational, not polish. Unblocks S2/S3/S5.
* Constraint identity is `constraint_key = constraint_name + '|' + contingency_name` (`panels.py:52-67`); SF index = these keys, SF columns = SPs.
* Dense storage is ~400 constraints × 1,084 SPs × ~52 refits ≈ 22M rows/run. Ship dense-per-refit + threshold-sparsified now; re-key to **groups × SPs** after S2 lands (two orders smaller).
* The plumbing hook already exists — `RefitWindow` carries `SF`, `M_window`, `C_window` to `on_refit_window` (`rolling.py:113-122`). This work is additive; no fit-path logic changes.

## Approach

* Work in: `db/migrations/`, `compute/sf/persist.py`, `compute/sf/runner.py`.
* Entry point / primary change: `on_refit_window` callback in `runner.py::main` → new `copy_sf_rows` / `write_window_meta` in `persist.py`.

**S0b.1 — Schema.** New migration `25_implied_shift_factors.sql`:
- `implied_shift_factors(run_id TEXT, window_start TIMESTAMPTZ, constraint_key TEXT, settlement_point TEXT, sf REAL, PRIMARY KEY (run_id, window_start, constraint_key, settlement_point))`. Index `(run_id, window_start)`.
- `sf_window_meta(run_id TEXT, window_start TIMESTAMPTZ, window_end TIMESTAMPTZ, score_start TIMESTAMPTZ, score_end TIMESTAMPTZ, n_kept INT, n_dropped INT, n_sf_clipped INT, fit_r2 REAL, coverage REAL, oos_r2 REAL, PRIMARY KEY (run_id, window_start))`. Leave `oos_r2`/`coverage` nullable — S1 fills them; S0b writes the in-sample `fit_r2` already available from `refit_diagnostics`.
- Follow migration 22's `CREATE TABLE IF NOT EXISTS` idempotent style; do NOT alter `implied_binding_proximity`.

**S0b.2 — Persist helpers** (`persist.py`, mirror `copy_bp_rows`/`delete_run`):
- `delete_sf_run(conn, run_id)` — clear both new tables for `run_id` (idempotent re-persist).
- `copy_sf_rows(conn, run_id, window_start, SF, threshold)` — unpivot `SF` (index=constraint_key, cols=SP), skip `|sf| < threshold` and non-finite, `COPY FROM STDIN`. Return row count.
- `write_window_meta(conn, run_id, window, meta_dict)` — one upsert row per refit.

**S0b.3 — Wire the runner:**
- Add `--persist-sf` (independent of `--persist`; sweeps stay off) and `--sf-threshold` (default e.g. `1e-3`).
- Inside `on_refit`, when the score period overlaps the requested range and `--persist-sf` is set, buffer `(window_start, SF)` and the meta fields already logged at `runner.py:213-220` (`n_kept`, `n_dropped`, `n_sf_clipped`, `fit_r2`).
- After the run, in one transaction: `delete_sf_run` → stream `copy_sf_rows` per window → `write_window_meta` per window → commit. Guard with `check_ref_method` like the bp path.
- Log rows-written and windows-written, same style as `runner.py:282`.

**S0b.4 — Verify** on a short range (e.g. `--start 2025-06-01 --end 2025-06-15 --persist-sf`) inside the compute container against the live db.

* Do NOT touch: `fit.py`, `metric.py`, `rolling.py` fit logic, `bp_ercot.npz` writing, or the `implied_binding_proximity` served path. Do NOT re-key to groups yet (that is S2).

## Acceptance

* [ ] Migration `25_*` applies cleanly and is idempotent; `\d implied_shift_factors` and `\d sf_window_meta` show the columns above.
* [ ] `python -m compute.sf.runner --run-id <id> --start … --end … --persist-sf` writes SF rows and exactly one `sf_window_meta` row per refit boundary in range.
* [ ] `SELECT count(*), count(DISTINCT constraint_key), count(DISTINCT settlement_point) FROM implied_shift_factors WHERE run_id=<id>` is non-trivial and matches the logged window/threshold counts.
* [ ] Re-running with the same `run_id` replaces (not duplicates) rows — count is stable.
* [ ] `bp_ercot.npz` and `implied_binding_proximity` outputs are byte-for-byte unchanged when `--persist-sf` is added (fit path untouched).
* [ ] `sf_window_meta.fit_r2` is populated; `oos_r2`/`coverage` present as nullable columns for S1.
