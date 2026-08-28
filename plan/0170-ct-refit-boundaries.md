# 0170 - CT refit boundaries

Type: fix
Branch: fix/0170-ct-refit-boundaries

## Goal

* Convert naive ERCOT delivery-day refit boundaries to the correct UTC instants before slicing hourly inputs.
* Keep weekly `geo`, `wx`, and outage-exposure fits aligned to CT midnight across DST.
* Regenerate and compare every μ artifact built with an affected feature arm.

## Context

* `delivery_day_of` returns a timezone-naive CT-midnight day label, while `M`, `C`, and system covariates are UTC-indexed.
* The three fitted feature arms currently label naive CT boundaries as UTC, shifting their fit windows five hours in CDT and six hours in CST.  In particular, `wx_panel` computes `lo_utc` from its incorrectly localized `s_utc`, and `outage_exposure_panel` localizes both `lo` and `s` as UTC before slicing `M_fit`/`C_fit`.
* This is conservative rather than future leakage, but it changes fitted features and makes existing affected model artifacts noncanonical after correction.

## Approach

* Work in: `compute/sf_map/geography/derive.py`, `compute/mu_forecast/covariates/weather.py`, `compute/mu_forecast/covariates/outages/exposure.py`, and their tests.
* Entry point / primary change: the weekly `for s in refit_grid(...)` loops that construct UTC slice bounds.
* Replace naive `tz_localize("UTC")` boundary handling with the shared CT-day-to-UTC conversion (`normalize_ct_day` or `ct_day_bounds`); preserve CT day labels for week assignment.
* In `wx_panel`, derive both `s_utc` and the preceding `lo_utc` from CT-local boundaries before slicing `M_win`; do not subtract the window from a boundary that was localized as UTC.
* In `outage_exposure_panel`, convert both `lo` and `s` from CT delivery-day boundaries to UTC before slicing `M_fit` and `C_fit`; leave its per-day outage-vintage selection unchanged.
* Add DST-aware regression tests proving CT midnight converts to 05:00 UTC in daylight time and 06:00 UTC in standard time, and proving each arm slices its fit window at that boundary.
* Rerun the walk-forward/prediction artifacts for every μ feature set containing `geo`, `wx`, or `out`; compare metrics and forecasts with the prior artifacts before any promotion.
* Do NOT touch: base/lag-only model behavior, raw-data ingestion, or unrelated SF-map persistence unless a separate audit finds it uses the same boundary pattern.

## Acceptance

* [x] Geography, weather, and outage-exposure weekly fit windows start and end at CT-midnight instants expressed in UTC, including both DST offsets.
* [x] `wx_panel`'s `M_win` begins at the CT-to-UTC-converted `lo` boundary and ends at the converted `s` boundary.
* [x] `outage_exposure_panel`'s `M_fit` and `C_fit` use the CT-to-UTC-converted `lo` and `s` boundaries, while its D−1 vintage rule remains intact.
* [x] Existing causality/no-future-data tests and new timezone-boundary regressions pass.
* [ ] Affected μ artifacts are regenerated and their before/after metrics and forecast deltas are recorded for review. Was blocked by the pre-existing `delivery_day_of` import regression (0165 refactor moved it to `compute.time`); fixed in the follow-up commit by repointing the three stale imports in `panel/engineering.py` and `sf_map/geography/derive.py` (x2). Regeneration still pending an env with `psycopg` installed; only the prior `mu-all-v1` artifact is available locally.
