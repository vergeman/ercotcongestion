# Representative Snapshot Sample

Type: perf
Branch: perf/0002-representative-snapshots
Status: Done

## Goal

* Extract dates that span seasonal date regimes, ordered by binding
* Persist those dates to json.
* Used to when tuning variables across regimes; ensure congestion is not from an
  adjustment factor, but a structural feature.

## Approach and Instructions

* Generate queries for:
  * 5 high-load summer-peak hours (most binding).
  * ~5 high-wind West-Texas hours (wind_factor_by_region->>'west' > 0.4.
  * ~5 mild shoulder hours (least binding).
  * ~3–5 winter-peak hours.
* Operate `/compute/profiling`
* Create in `/compute/profiling/sample_snapshots.py`
* Output date JSON to `reference_snapshots.json.`
