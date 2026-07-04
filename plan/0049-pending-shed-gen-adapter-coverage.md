# 0044 - shed-gen-adapter-coverage

Type: fix
    Branch: fix/0049-shed-gen-adapter-coverage

## Goal

* Stop `stack_time_varying` from flagging `shed_*` pseudo-generators as "escaped adapter coverage" and throttling them to `p_max_pu=0.8`.
* Load-shed pseudo-generators must run with `p_max_pu=1.0` on every snapshot so the OPF's shed ceiling matches the intended `p_nom`.
* Eliminate the 2,751 warning lines per snapshot that dominate recompute logs.

## Context

* `_ensure_load_shed_gens` (`compute/snapshot.py:133`) adds 2,751 `shed_<bus_id>` generators (`carrier="load_shed"`) as an infeasibility safety valve. They are pseudo-generators, not ERCOT resources, and are intentionally absent from `generator_matches_enriched.csv`.
* `stack_time_varying` (`compute/operating_conditions.py:67`) diffs `n.generators.index` against the adapter's `per_gen.index`, treats every unmatched generator as "escaped coverage", and fills `p_max_pu` with `DEFAULT_P_MAX_PU['other'] = 0.8`.
* Consequence: shed capacity is throttled to 80% of `p_nom`, biasing stressed hours where the OPF actually shed. Non-shed hours are unaffected numerically but every hour pays the log I/O cost.
* Pre-existing since `f14efb0` (Feat/0010 batch pypsa, 2026-06-28). Surfaced now because the B4 full-year recompute made the log volume impossible to ignore.

## Approach

* Work in: `compute/operating_conditions.py`
* Entry point: `stack_time_varying` — the `missing = n.generators.index.difference(per_gen.index)` block around lines 67–73.
* Import `SHED_PREFIX` from `compute/snapshot.py` (or duplicate the literal `"shed_"` — this file already knows about network conventions; a small `from snapshot import SHED_PREFIX` keeps one source of truth).
* Partition `missing` into `shed_missing` (names starting with `SHED_PREFIX`) and `unexpected_missing` (everything else).
  * For `shed_missing`: fill their `p_max_pu` with `1.0`, do NOT warn — this is by design.
  * For `unexpected_missing`: warn as today with the existing message and `other_default` fallback. Preserve the current diagnostic for any real coverage gap.
* Verify by running one snapshot: log should be silent on shed_ and `n.generators_t.p_max_pu` should show `1.0` for every `shed_*` column, `≤ carrier_default` for real gens.
* Do NOT touch: `compute/snapshot.py` load-shed setup (`_ensure_load_shed_gens`), the adapter's `p_max_pu_per_gen` construction, or the parallel `apply_operating_conditions` helper — it's used only by experiment scripts, not the batch path B4 exercises. Optional cleanup to that helper can piggyback but is not required.

## Acceptance

* [x] One-snapshot run of `compute/write_snapshots.py` produces zero `escaped adapter coverage` warnings when only `shed_*` gens are missing.
* [x] A synthetic test where a non-shed gen is deliberately removed from adapter coverage still emits the warning (regression guard on the real diagnostic).
* [x] Post-fix `n.generators_t.p_max_pu` shows `1.0` for every `shed_*` column across the chunk.
* [x] B4 full-year recompute log size drops to the pre-shed pattern (spot check: <1 MB per 100 snapshots vs. the prior ~50 MB).
* [x] No change to `bus_snapshots` / `snapshot_meta` schema; no writer changes required.
