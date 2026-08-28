# 0172 - outage crosswalk coverage names

Type: refactor
Branch: refactor/0172-outage-crosswalk-coverage-names

## Goal

* Replace opaque `GATE_C_*` threshold names with MW-location-coverage names.
* Preserve the existing 60% build and 30% flagged-subset decisions.

## Context

* Gate C means the resource-to-settlement-point join, but that meaning is not apparent at call sites.
* These thresholds evaluate the MW-weighted share of outage records that can be located.

## Approach

* Work in: `compute/mu_forecast/covariates/outages/crosswalk.py`, `compute/probes/outage_crosswalk.py`, and `compute/probes/outage_feed.py`.
* Rename threshold constants to describe locatable-outage-MW coverage and update imports, decisions, and printed labels in all three locations.
* Do NOT change threshold values, matching behavior, or verdicts.

## Acceptance

* [x] No `GATE_C_*` identifiers remain in the three scoped modules.
* [x] The build/flagged/dead outcomes remain 60% / 30% / below 30%.
