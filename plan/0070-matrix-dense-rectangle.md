# 0070 - matrix-dense-rectangle

Type: fix
Branch: fix/0070-matrix-dense-rectangle

## Goal

* Replace the current all-or-nothing hour pruner in `compute/matrix.py` with a
  sweep that picks the largest dense (SP subset × hour subset) rectangle.
* On the v1-annual run, keep ≥95% of hours (target: ~8,500+) instead of the
  current 475, by trading off a small number of late-arriving SPs.
* Emit an `hours_kept_vs_sps_kept` curve to the matrix log so the sweep's
  chosen cutoff is inspectable.

## Context

* Root cause: `_prune_structural_hours` in `compute/matrix.py:296` drops any
  hour where *any* surviving SP is NaN. New settlement points (batteries,
  solar) go live throughout the year — 112 of 1,071 SPs first published
  after Jan 1, 2025; the last 5 first appeared on 2025-12-11 06:00 UTC.
  This kills 94.6% of the annual window (8,253 of 8,728 hours).
* The bus-side filter (matrix.py:~L120-ish, "dropped 157 bus(es) with NULL
  lmp") is already strict — surviving buses have zero NaN cells, so they
  don't contribute to hour drops. This fix is entirely SP-side.
* SP NaN pattern is nearly monotonic (once an SP goes live it stays live),
  so the general NP-hard "max fully-dense rectangle" problem collapses to a
  1-D sweep: sort SPs by first-seen ascending, and for each cutoff k
  compute `n_hours(k) × (n_sp - k)`. Pick the argmax (or a knee-of-curve).
* Reference run: v1-annual on the `ercotstress` namespace `compute-shell`
  pod (`/compute/runs/v1-annual`). Meta.json's `dates_file` is
  `/compute/sample_specs/flat_dates_2025-01-01_2026-01-01.json` (8,728
  hours). Scorecard headline currently reports `n_hours=475, n_zones=3`.
* Design tradeoff already flagged in `matrix.py:308-312`: the current
  pruner was written for 3-day dense runs where "trade a few hour columns
  for the row axis" was correct. At year scale that assumption inverts.

## Approach

* Work in: `compute/matrix.py`
* Entry point / primary change: replace `_prune_structural_hours`
  (matrix.py:296) with `_select_dense_rectangle`.
* Step 1 — After both matrices are populated and the "no coverage anywhere"
  SP filter has run (matrix.py:272-291), compute per-SP `first_valid_hour`
  and per-SP `last_valid_hour` from the structural NaN mask (NaN in every
  ref method). Assume monotonic coverage: if it isn't monotonic for a
  given SP (rare, e.g. a gap in the middle), fall back to counting that SP
  as "never fully covered before its last gap."
* Step 2 — Sort SPs by `first_valid_hour` ascending. Sweep the cutoff `k`
  from 0 (drop nothing, keep 475 hours) to `n_sp` (drop everything). For
  each k, `n_hours_kept(k) = total_hours - max(first_valid_hour[j] for j >= k)`
  and `n_sp_kept(k) = n_sp - k`. Product is the rectangle area.
* Step 3 — Selection rule: pick the k that maximizes area, with a
  configurable `--min-sp-fraction` guard (default 0.90) so we don't strip
  the SP axis to chase hours. Expose `--sp-coverage-strategy {max_area,
  max_hours, threshold}` where `threshold` reproduces old behavior (k=0).
* Step 4 — Log the full curve: for each interesting cutoff (the argmax and
  each ±5% inflection), print `k=<n>, n_sp=<n>, n_hours=<n>, area=<n>,
  latest_kept_sp_first_seen=<ts>`. Include the identities of dropped SPs
  in a preview list, same style as the existing SP drop message.
* Step 5 — Apply the chosen cutoff: drop those SPs from `ercot_C` and
  `sp_ids`, then drop hours before the latest surviving `first_valid_hour`.
  The resulting rectangle is fully dense — downstream code needs zero
  changes.
* Step 6 — CLI flags on `compute/matrix.py` main (argparse near L394+):
  `--sp-coverage-strategy` (default `max_area`), `--min-sp-fraction`
  (default 0.90), `--sp-coverage-strategy=threshold` retains today's
  behavior for reproducibility of existing runs.
* Step 7 — Tests in `compute/tests/` (create test file if none exists for
  matrix, following the pattern in `compute/clustering/tests/`): (a) fully
  dense input → no drops; (b) one late SP → sweep finds cutoff=1 correctly;
  (c) monotonic ladder of 5 SPs starting on 5 different dates → verifies
  area calculation and choice; (d) non-monotonic SP (gap in middle) is
  treated conservatively; (e) `threshold` strategy reproduces old
  all-or-nothing behavior.
* Do NOT touch: any of `compute/mapping/`, `compute/clustering/`, or
  `compute/mapping/scorecard.py`. The whole point of this fix is that the
  downstream contract (fully-dense rectangle in the npz) is preserved. If
  you find yourself modifying anything under `compute/mapping/` or
  `compute/clustering/` to make this work, stop — the plan is wrong.

## Acceptance

* [ ] Re-running the annual pipeline (v1-annual spec, same dates_file
      `flat_dates_2025-01-01_2026-01-01.json`) produces a
      `congestion_matrices.npz` with `n_hours ≥ 8000` and `n_sp ≥ 950`
      under the default `max_area` strategy.
* [ ] The resulting matrices are still 100% dense (no NaN cells) in the
      non-`system_lambda_merit_order_ercot_C` reference methods.
* [ ] Scorecard headline `n_hours` reported in
      `mapping/scorecard_v1-annual.json` reflects the new hour count and
      the run picks up seasonal coverage — verify by inspecting
      `system_lambda_merit_order_model_hours[0]` and `[-1]` span multiple
      months, not just December 2025.
* [ ] Matrix log includes the sweep table (at minimum: chosen k, n_sp_kept,
      n_hours_kept, area, and the top 3 alternative cutoffs).
* [ ] `--sp-coverage-strategy=threshold` reproduces the pre-fix behavior
      byte-for-byte on the v1-annual input (regression test).
* [ ] Downstream stages (basis_regression, correlation_map, cca,
      clustering, scorecard) run through without code changes and without
      new NaN-handling warnings.
* [ ] New unit tests pass; existing matrix-adjacent tests still pass.
