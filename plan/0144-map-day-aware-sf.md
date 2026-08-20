# 0144 - map-day-aware-sf

Type: fix
Branch: fix/0144-map-day-aware-sf

## Goal

* Add a delivery-day parameter to `/map/exposures` and `/map/reach`; both
  currently ignore time entirely.
* Serve both from the per-day SF artifact — the same object `/matrix/frame` and
  `/map/constraints/ranked` read — so the map matches the matrix exactly.
* Return an explicit empty-with-reason for days with no artifact.

## Context

* `_resolve()` (`api/map.py:104`) always takes `max(window_start)` from
  `sf_window_meta`, so the DetailCard shows the newest rolling fit
  (`2025-12-20 → 2026-08-17`) whatever `t` the URL carries. For `t=2025-02-20`
  the served constraint list is fully disjoint from the matrix's.
* The window covering Feb 2025 (`ws=2024-06-29`) gives the same constraints,
  signs and order as the artifact — confirming the mismatch is stale window
  selection, not a modelling difference.
* `/map/constraints/ranked` already takes `day` and reads the artifact, so the
  ranked sidebar and the DetailCard are on different time bases today.
* Artifacts (`mu-all-v1`, horizon 1) cover 2025-01-01 → 2026-08-20 with no gaps.
  Map windows reach further back (2024-05-04); those days lose map SF.
* `oos_r2` / `sf_stability` are window-fit diagnostics with no artifact analogue.
  DetailCard does not read them.

## Approach

* Work in: `api/map.py`, `api/models.py`, `web/src/api/client.ts`,
  `web/src/workspaces/MapWorkspace.tsx`,
  `web/src/components/panels/ConstraintReach.tsx`,
  `web/src/components/brief/BriefFootprintMap.tsx`.
* Entry points: `get_map_exposures`, `get_map_reach`.
* Add `t: datetime | None` to both. Resolve the CT delivery day with the shared
  helper (0143.1: CT date, never UTC) and load via `load_daily_artifact`. Omitted
  `t` → the run's latest artifact day.
* Extract `_delivery_date` out of `api/matrix.py` into `services/sf_artifacts.py`
  so map and matrix cannot drift on the day cut again.
* Read SF from `artifact.SF`: exposures = the `sp` column, reach = the
  `constraint` row, both ranked by `|sf|`. Keep reach's `min_frac` floor, taken
  off the artifact row's own peak.
* Derive per-day fields from the artifact, matching what `/matrix/frame` already
  reports: `max_abs_sf` from the SF row, `binding_hours` from
  `(E_mu[key].abs() > 0).sum()`, `node_max_abs_sf` from the SF column.
* `ctype`, `n_rail`, `peak_offrail` stay best-effort from `constraint_geo`
  (latest window, the `DISTINCT ON … ORDER BY window_start DESC` pattern already
  in `matrix._constraint_types`) — structural metadata, not day-specific.
* Set `window_start`/`window_end` to the artifact block's bounds so the response
  still describes its own basis; `oos_r2`/`sf_stability` become `None`.
* Add `available` + `unavailable_reason` to `ExposuresResponse` (`ConstraintReach`
  already has `available`). No artifact for the day → 200 with `available: false`,
  not 503.
* Frontend: thread the cursor day through `fetchMapExposures`/`fetchMapReach`;
  key `ConstraintReach`'s module-side `reachCache` on `day|constraint`, not
  `constraint`; pass the Brief's day from `BriefFootprintMap`.
* Do NOT touch the map's rolling SF fit itself (`sf_window_meta`,
  `implied_shift_factors`, `compute/jobs/weekly_map.py`) — `/map/overview`,
  `/map/meta` and `/map/summary` keep using it.

## Acceptance

Verified end-to-end against the dev stack (`docker compose`, delivery day
2026-08-13, node `THREEW_S_RN`, constraint `HARGRO_TWINBU1_1|SRUSBIG8`).

* [x] `/map/exposures` returns the same SF as `/matrix/frame` at the same node
      and interval — 10/10 constraints match to the matrix's 3dp rounding.
* [x] `/map/reach` likewise — 8/8 nodes match, and the fields moved off
      `constraint_geo` onto the artifact agree exactly (`max_abs_sf` 0.847,
      `binding_hours` 24).
* [x] Map and matrix agree on *availability* at every probed hour, including the
      CT-evening seam.
* [x] A day with no artifact returns `available: false` /
      `artifact_missing`; an unknown constraint returns
      `constraint_not_in_artifact`; an unknown node stays `available` with an
      empty list (the pre-existing soft-fail).
* [x] Omitting `t` serves the latest built day.
* [x] `ConstraintReach`'s two caches and `MapWorkspace`'s `focusReachCache` key
      on delivery day + constraint.
* [x] `api/tests`: 135 passed; only the 3 pre-existing `test_analysis.py`
      failures (0143.2) remain, unchanged.
* [x] `web`: `tsc --noEmit` clean, build succeeds, eslint 16 findings — exactly
      HEAD's baseline, no new ones.

## Notes for the prod rollout

* **Dev data is not representative.** Dev artifacts are UTC-day blocks
  (00:00Z→23:00Z) and share one identical SF matrix across every day — only
  `E_mu` varies. Prod's are CT blocks (05:00Z→04:00Z) with per-day SF. So dev
  can prove map==matrix and the availability contract, but *cannot* show the
  day-to-day list change that motivated this plan. Re-check the original URL
  pair on prod after deploy.
* An hour the block does not cover is now unavailable on the map, matching
  `/matrix/frame`. On correctly cut CT blocks this never fires (a block covers
  all 24 of its day's hours); it exists so a misaligned or partial block cannot
  make the map and matrix disagree.
