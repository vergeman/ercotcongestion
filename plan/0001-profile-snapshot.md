# 0001 - profile one snapshot

Type: perf
Branch: perf/0001-profile-snapshot
Status: Completed

## Goal

* Produce a timing breakdown for a single representative snapshot run.
* profile and isolate expensive calculation paths, I/O, etc.

## Approach and Instructions

* Add timing output throughout a test_snapshot.py run
* Look at code path and add timing output at each dependency

* keep only in /compute sub-directory - only concerned with the snapshot
  calculation

## Result

 ┌─────────────────────────┬───────────────────┬────────────────────┬──────────────────────┬─────────────────────┐
 │                         │ output-1 (post-A) │ output-2 (Step1+2) │ output-3 (post_proc) │ output-4 (topology) │
 ├─────────────────────────┼───────────────────┼────────────────────┼──────────────────────┼─────────────────────┤
 │ ptdf.determine_topology │ 7.8 s             │ 5.7 s              │ 6.9 s                │ 0.47 s              │
 ├─────────────────────────┼───────────────────┼────────────────────┼──────────────────────┼─────────────────────┤
 │ compute.get_ptdf_lodf   │ 15.4 s            │ 12.8 s             │ 17.1 s               │ 6.8 s               │
 ├─────────────────────────┼───────────────────┼────────────────────┼──────────────────────┼─────────────────────┤
 │ run_snapshot_for_ts     │ 107.5 s           │ 59.4 s             │ 43.0 s               │ 23.6 s              │
 └─────────────────────────┴───────────────────┴────────────────────┴──────────────────────┴─────────────────────┘
