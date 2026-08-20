# 0146 - map-node-not-in-fit

Type: fix
Branch: fix/0146-map-node-not-in-fit

## Goal

* Give `/map/exposures` its own `unavailable_reason` when a node has no SF on the requested day.
* Split that into `sp_not_in_service` (node did not exist yet) and `sp_not_in_fit` (existed, fit dropped it).
* Badge the DetailCard header with that state instead of rendering "Nothing bound this hour".

## Context

* Nodes enter ERCOT's feed in batches (7 on 2026-05-02, incl. `PDRA_SLR_RN`, `GRND_SLR_RN`); pins come from the static geocoded CSV, so they are clickable on days before the node existed.
* That case returned `available: true`, `exposures: []` — identical in shape to "in the fit, nothing bound", so the UI mislabelled it.
* A day's fit is a subset of its nodal forecast (1111 vs 1120 on 2026-06-30), e.g. `CPSES_UNIT1` — so "absent from the fit" is not always "did not exist".
* No commissioning date is served: `min(interval_ts)` per settlement point on `ercot_dam_spp` measures ~1.7s (86 partitions, no supporting index). Out of scope.

## Approach

* Work in: `api/map.py`, `api/models.py`, `api/tests/test_map.py`, `web/src/api/types.ts`, `web/src/components/map/DetailCard.tsx`
* Entry point: `get_map_exposures` — the `sp not in artifact.SF.columns` branch.
* Return `available=False` there, with the reason from a new `_absent_sp_reason`; keep `window_start`/`window_end` as the artifact's own bounds.
* `_absent_sp_reason`: one `forecast_nodal` count for the run/day, `sp_rows` vs `day_rows` — no rows for the node on a day the run did forecast means not in service. `day_rows = 0` is ambiguous, so it falls back to `sp_not_in_fit`.
* `web/src/api/types.ts`: narrow `unavailable_reason` to the four literals.
* `DetailCard.tsx`: `Non-existent` / `Not in fit` as a warning chip in the header, top right opposite the node id; suppress the drivers section in that state. Match on `exposures.sp === sp.spId` so a stale response cannot mislabel the next node.
* Do NOT touch: pin rendering / map universe filtering, `/map/reach`, `/matrix/*`, the SF fit.

## Acceptance

* [x] A node absent from the day's fit returns `available: false` with `sp_not_in_service` or `sp_not_in_fit`, never an empty available list.
* [x] Dev API at `t=2026-06-30T18:00:00Z`: `ZZZ_FAKE_RN` → `sp_not_in_service`, `CPSES_UNIT1` → `sp_not_in_fit`, `HB_HOUSTON` → `available: true`.
* [x] A node in the fit that binds nothing at `t` still returns `available: true`, `unavailable_reason: null`.
* [x] `tests/test_map.py` covers all three count shapes incl. the `day_rows = 0` fallback; suite green.
* [x] `tsc --noEmit -p tsconfig.app.json` clean.
* [ ] DetailCard shows the uppercase warning chip top right, no driver rows: `http://localhost:5173/map?sp=CPSES_UNIT1&t=2026-06-30T18Z&ws=2026-06-30T00Z&we=2026-06-30T23Z&view=forecast&data=congestion`
* [ ] After deploy: `sp=PDRA_SLR_RN&t=2026-04-28T22:00:00Z` → `sp_not_in_service`; same node at `2026-08-17T22:00:00Z` → `available: true`.
