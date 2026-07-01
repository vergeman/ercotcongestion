# B4 - full-year-congestion-recompute

Type: chore
Branch: chore/full-year-congestion-recompute

## Goal

* Recompute the full Sprint-1 window with the new metrics writing `modeled_congestion` + `binding_proximity` on every `status='ok'` row.
* Retain ≥ 99% of Sprint-1 baseline `status='ok'` count (regressions imply a metric bug).
* Log per-hour rate, ETA, and RSS to catch cost regressions early.

## Context

* This is the load-bearing operational cost of the sprint (§6 of sprint2a-plan.md).
* Depends on B3's sample-recompute-gate returning GO.
* Not a code PR - an ops action logged in the plan. `--force-recompute` flag from B2 is the enabling change.
* Window: same range Sprint-1's most recent full-year populate used. Confirm via `SELECT min(interval_ts), max(interval_ts) FROM snapshot_meta WHERE status='ok'` before kickoff.

## Approach

* Work in: ops (no code changes).
* Kickoff: `python -m compute.write_snapshots --start <sprint1_min> --end <sprint1_max> --force-recompute` (in the batch env - see `ops/deploy/jobs/backfill_pricing_job.yml` pattern).
* Monitor:
  * Per-chunk log line with rate (snapshots/min) and ETA.
  * RSS via existing `_clear_time_varying` telemetry - should stay flat.
  * Per-hour compute cost vs Sprint-1 baseline; abort and profile if > 2× baseline.
* On completion, SELECT baseline vs current `status='ok'` counts and record delta.
* Do NOT run Migration B (drop `fragility*` columns) here - that waits for 2B + 2C.

## Acceptance

* [ ] Every snapshot in the Sprint-1 window has `modeled_congestion` and `binding_proximity` populated on `status='ok'` rows.
* [ ] `status='ok'` retention ≥ 99% of Sprint-1 baseline count.
* [ ] Compute cost per hour ≤ 2× Sprint-1 baseline (documented in a short runbook append).
* [ ] `snapshot_meta` `fragility_total` / `fragility_top10_share` are NULL on all newly-written rows in the window.
* [ ] Recompute run + timing recorded in `plan/full-year-congestion-recompute.md` (append results block after run).
