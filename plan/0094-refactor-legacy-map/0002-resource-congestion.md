# 0094-0002 - re-source Congestion off the legacy artifacts

Type: refactor
Branch: refactor/0094-0002-resource-congestion

> THE GATE. `0003` and `0004` cannot proceed until `/ercot_state_range` stops reading
> `served_run_dir` / `matrix` / `mapping`. Confirm the sourcing decision below first.

## Goal

* Serve `/ercot_state_range` (Congestion = `SPP − system_λ`) from the DB at request
  time, removing its reads of `served_run_dir/matrix/congestion_matrices.npz` and
  `mapping/scorecard.json`.
* Keep the `ErcotStateRangeResponse` shape byte-identical so `web/` is unchanged.

## Context

* Today `api/ercot_state.py` loads a per-ref congestion matrix baked by
  `compute/legacy/matrix.py` + `mapping`, and reads `params.ref` from the served
  `scorecard.json` — the last legacy coupling on the Congestion path.
* The DB already holds the inputs: `SPP` (`ercot_dam_spp`, served raw by
  `/ercot_spp_range`) and `system_λ` (`dam_system_lambda`). `SPP − system_λ` is exactly
  what `compute/sf/panels.load_congestion_panel(ref_method="system_lambda")` computes.
* DECISION (confirm before building): **(A, recommended)** re-source from the DB as
  below; **(B)** retire `/ercot_state_range` entirely if Congestion is folding into the
  SF layer (`-Σ SF·μ`); **(C)** keep the frozen legacy artifact and remove only the
  clustering/scorecard-cell parts (leaves `served_run_dir` + matrix + scorecard alive,
  blocking most of `0003`/`0004`). This plan assumes **A**.

## Approach

* Work in: `api/ercot_state.py`, `api/tests/test_ercot_state.py`.
* Replace the npz/scorecard reads with a DB query mirroring `api/ercot_spp.py`
  (pool + `dict_row`): pull `ercot_dam_spp` and `dam_system_lambda` over `[start, end]`,
  compute `congestion = spp − system_λ` per `(interval_ts, settlement_point)`, and emit
  the existing `ErcotStateRangeEntry` / `ErcotSpState` shape. Reuse the SPP
  dedup/collapse `compute.ercot.transforms.fetch_dam_spp_batch` uses.
* Fix the ref to `system_lambda` (distributed slack — what the map + forecast use);
  drop `_read_served_ref`, `_REF_CACHE`, `_matrix_path`, `_scorecard_json_path`, and the
  `served_run_dir` / `numpy` imports.
* Keep the soft-fail contract: an empty range → 503 (client maps 503 → null).
* Do NOT touch: `ErcotStateRangeResponse` field names/types, `/ercot_spp_range`, `web/`.

## Acceptance

* [ ] `/ercot_state_range` returns Congestion computed from the DB; response shape
  unchanged; `web/` renders it with no client change.
* [ ] `grep -rn served_run_dir api/ercot_state.py` returns nothing; the endpoint no
  longer touches `matrix/` or `mapping/`.
* [ ] Spot-check: a window's values match the old baked matrix (same `SPP − system_λ`)
  within float tolerance.
* [ ] After this + `0001`, `grep -rn served_run_dir --include=*.py api/` returns only
  removable references (feeds `0003`).
* [ ] `pytest api/` green.
