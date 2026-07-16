# 0006 - web-data-fixes

Type: fix
Branch: fix/0006-web-data-fixes

## Goal

* Fix RGV battery geocodes mis-placed on a shared Waco placeholder.
* Stop the constraint overlay from hiding the reach glow on click.
* Floor the reach and flag weakly-fit constraints so noise doesn't read as signal.

## Context

* `VALEXP`/`SCARBI` inspection surfaced two problems: bad geocodes, and low-support constraints whose SF is a ridge artifact (clipped ±1, <50 binding h).
* Centroid overlay is a lossy summary; the SF reach is the truth — see `docs/ERCOT_constraints.md`.
* No SP-coordinate table exists in the DB; SP coords live only in the geocoded CSV. `constraint_geo` is derived.

## Approach

* Geocode: fix 4 nodes (`W_HRL_ESR_RN`, `SROSA_ESR_RN`, `MYRY_ESR_RN`, `MYRY_BES2_RN`) in `data/raw/ercot_geocode/manual_overrides.csv` + `data/processed/settlement_points_geocoded.csv` from EIA-860; recompute `constraint_geo` via `compute.sf.geo_persist --run-id map-v1`.
* Reach fade: in `GridMap.tsx`, drop `constraint-markers` opacity while `reach` is set (add `reach` to the overlay effect deps).
* Reach floor: `GET /map/reach` gains `min_frac` (default 0.05); drop `|SF| < min_frac·peak`.
* Low-confidence: badge overlay markers muted (`binding_hours < 50` or `max_abs_sf ≥ 0.999`); surface `binding_hours` + clip status in the reach detail card (thread `binding_hours` through `ConstraintReach`).
* Do NOT touch: the SF fit / model, other endpoints, the pre-existing web tsconfig lib errors.

## Acceptance

* [x] Four nodes return RGV coords from `/map/reach`; `constraint_geo` recomputed (80,602 rows).
* [x] Pinning a constraint fades the overlay; nodes glow visible.
* [x] `SCARBI_TITAN` reach returns 6 nodes (was ~15); `VALEXP` unchanged at 15.
* [x] `SCARBI_TITAN` renders muted + "low confidence"; card shows `clipped ±1` and binding h.
* [x] `tests/test_map.py` passes; `docs/ERCOT_constraints.md` documents naming, types, and noise ID.
