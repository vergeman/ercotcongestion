# 0081 persist-sf-matrix — DONE

Type: feat · Branch: feat/0081-persist-sf-matrix

## Goal

Persist the per-refit `SF` matrix (constraint×SP) that `rolling_bp` computes and
discards — only the scalar `bp = max_c|SF|` survived (migration 22). Every v3
surface (node explorer, `congestion = −Σ SF·μ̂`, coverage decomp, grouping)
needs the full matrix. `constraint_key = constraint_name|contingency_name`.

## Changes

* **`db/migrations/25_implied_shift_factors.sql`** — two idempotent tables:
  - `implied_shift_factors(run_id, window_start, constraint_key, settlement_point, sf)`, PK all four, index `(run_id, window_start)`.
  - `sf_window_meta(run_id, window_start, window_end, score_start, score_end, n_kept, n_dropped, n_sf_clipped, fit_r2, oos_r2, coverage)`. `oos_r2`/`coverage` nullable — **S1** backfills. `constraint_key` free-form TEXT so the S2 group re-key needs no migration. `db/export_prod_database.sh` TABLES list updated.
* **`compute/sf/persist.py`** — `delete_sf_run`, `copy_sf_rows` (unpivot, skip `|sf|<threshold`/non-finite, `COPY FROM STDIN`), `write_window_meta` (upsert on PK).
* **`compute/sf/runner.py`** — `--persist-sf` (independent of `--persist`) + `--sf-threshold` (default `1e-3`). Streams each window to the DB inside `on_refit` in one transaction (opened after `check_ref_method` + `delete_sf_run`, committed after the fit). No buffering.

Untouched: `fit.py`, `metric.py`, `rolling.py` fit logic, `bp_ercot.npz`, the
`implied_binding_proximity` served path. Group re-key deferred to S2.

## Acceptance — all verified (`--start 2025-06-01 --end 2025-06-15`)

* [x] Migration applies + idempotent; `\d` shows the columns above.
* [x] Writes SF rows + exactly one meta row per refit — 3 windows → 3 meta rows.
* [x] Cardinality matches logs — 1,279,855 rows, 502 constraints, 1012 SPs; `min|sf| = 0.00100` (threshold), `sf ∈ [−1,1]` (cap).
* [x] Re-run replaces not duplicates — cleared 1,279,855+3, rewrote identical counts.
* [x] `bp_ercot.npz` byte-for-byte identical with/without `--persist-sf`; `implied_binding_proximity` path unaffected.
* [x] `fit_r2` populated (≈0.983); `oos_r2`/`coverage` NULL for S1.

## Note for S1

`fit_r2 ≈ 0.983` is **in-sample** (lookahead window `window_end = score_end`) —
the number the OOS harness flags as inflated (0.986 → 0.746 honest). S1 makes
the honest window a fit mode and fills the nullable `oos_r2`/`coverage`.
