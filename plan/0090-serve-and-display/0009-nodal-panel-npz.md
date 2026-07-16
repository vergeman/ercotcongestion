# 0009 - nodal-panel-npz

Type: feat
Branch: feat/0009-nodal-panel-npz

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Emit the backtest nodal panel as a flat, vocab-coded npz via a new `--nodal-out PATH.npz` flag on `propagate`'s CLI, streamed one week at a time.
* Provide `save_nodal`/`load_nodal` round-tripping the flat columns `ts, sp_code (+ sp_vocab), p10, p50, p90, point` (+ `week`), mirroring `mu_model.save_preds`/`load_preds`.
* With no new flag, `walk()`'s outputs and `mu_bands_weekly.csv` are unchanged.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase2a-nodal-panel.md` §2 (flat vocab-coded npz, not parquet/dense), §5(a) (offline artifact), §8 (CLI), §9 (size). Depends on **0008** (`propagate_window` + `NodalPanel`); do that branch first.
* The node set (`SF.columns`) is ragged across weeks — store **flat 1-D columns**, never a dense `(T,N,3)` array that forces a union-and-fill. This matches the repo's existing panel idiom (`key_vocab`+`key_code` in `mu_model`).
* This artifact is the record of the full backtest panel (~7.5M rows ≈ 120 MB f32, spec §9), backs the Phase-4 historic slider, and seeds `forecast_nodal` in bulk (0010).
* Streaming keeps peak memory at one week (~2 MB of percentiles), never the 45-week concat (spec §9).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `compute/mu/propagate.py` (CLI + accumulator); put `save_nodal`/`load_nodal` beside the panel code (propagate.py, or mirror them next to `mu_model.save_preds` — keep with `NodalPanel`).
* **Accumulator, streamed per week.** After `propagate_window(..., want_panel=True)` returns a `NodalPanel`, flatten it to columns `(ts int64 µs, sp_code, p10, p50, p90, point, week)`, mapping `settlement_points → sp_code` against a growing `sp_vocab`. Append to a per-week buffer; do not concat all weeks in memory.
* **`--nodal-out PATH.npz`** (spec §8): when set, `emit=True` is threaded into the `walk()` loop so each week calls `propagate_window(want_panel=True)` and the panel is streamed to the npz sink; when unset, `want_panel=False` and nothing changes. Keep the existing `--out`/`--preds`/`--scores`/`--seed` args intact and default-unchanged.
* **`save_nodal(path, cols, sp_vocab)`** — `np.savez` of flat arrays + `sp_vocab` string array, same encoding as `save_preds`. **`load_nodal(path) -> DataFrame`** — inverse, decodes `sp_code→settlement_point`, returns tz-aware UTC `ts`.
* `week` retained as a column for the historic slider (spec §5a).
* Drivers stay **off** here — full-history drivers are ~75M rows (spec §2.4, §5a). No `--drivers`, no SF+μ artifact (that is 0011).
* Do NOT touch: `band_metrics`, `r5()`, `forecast_nodal`/any DB (0010), the metrics CSV path.

## Commits

<!-- Grouped so the CLI runs and the npz round-trips at branch end. -->

* **Commit A — `feat(propagate): save_nodal/load_nodal flat vocab-coded npz`**
  * `propagate.py` — `save_nodal`/`load_nodal` + the flatten helper `NodalPanel → (ts, sp_code, p10, p50, p90, point, week)`.
* **Commit B — `feat(propagate): --nodal-out streams the panel per week`**
  * `propagate.py` — CLI `--nodal-out`; thread `emit` into the `walk()` loop, `want_panel=True` only when emitting, stream to the sink. No-flag path byte-identical.
* **Commit C — `test(propagate): nodal npz round-trip + no-flag invariance`**
  * `compute/mu/tests/` — `save_nodal`→`load_nodal` recovers `ts`/SP/percentiles/`point`; `load_nodal` node axis for a week `== SF.columns`; running without `--nodal-out` leaves `mu_bands_weekly.csv` byte-identical.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `python -m compute.mu.propagate --nodal-out out.npz` writes a flat vocab-coded npz; without it, no npz and `mu_bands_weekly.csv` is byte-identical to 0008's baseline.
* [ ] `load_nodal(out.npz)` returns tz-aware UTC `ts`, decoded `settlement_point`, and `p10/p50/p90/point` matching the in-memory `NodalPanel` for a spot week.
* [ ] Peak memory during emission is ~one week of percentiles, not the full concat (streamed accumulator, spec §9).
* [ ] Full-backtest npz row count ≈ weeks × hours × SPs; `point` column present and distinct from `p50`.
* [ ] `pytest compute/mu/tests/` green; no DB writes, no driver rows.
