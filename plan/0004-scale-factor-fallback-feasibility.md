# 0004 - scale factor fallback feasibility

Type: feat
Branch: feat/0004-scale-factor-fallback-feasibility

## Goal

* Feasibility fallback wrapper (in snapshot.py or adapter caller): attempt solve
  with zonal-scaled loads.

* If n.optimize() returns infeasible, fall back to global scaling for that
  snapshot and log it.

* Emit load_scaling_mode into snapshot_meta (zonal | global_fallback).

* Come up with some retry logic if this is the case

## Context

* Our prior commit used zonal scale factor with a global scale factor fallback -
  if the data was unavailable.

* Now we want to build in some robustness, and use the global scale factor if we
  encounter infeasibility (not just bad data) when using zonal scale factors.

* Infeasibility is an expected, reportable finding (TAMU topology can't always
  carry ERCOT's real geography), not a bug.

## Approach and Instructions

* Keep in /compute directory
* Focus in snapshot.py, or operating_data_adapter.py
