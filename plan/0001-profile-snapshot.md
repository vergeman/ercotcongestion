# 0001 - profile one snapshot

Type: perf
Branch: perf/0001-profile-snapshot
Status: Not started

## Goal

* Produce a timing breakdown for a single representative snapshot run.
* profile and isolate expensive calculation paths, I/O, etc.

## Approach and Instructions

* Add timing output throughout a test_snapshot.py run
* Look at code path and add timing output at each dependency

* keep only in /compute sub-directory - only concerned with the snapshot
  calculation
