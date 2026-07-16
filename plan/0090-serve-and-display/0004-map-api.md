# 0090.0004 - map-api

Type: feat
Branch: feat/0004-map-api

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Serve `GET /map/meta`, `/map/constraints`, `/map/exposures?sp&k`, `/map/reach?constraint&k` off `sf_window_meta` / `constraint_geo` / `implied_shift_factors`.
* Resolve the served run + current refit by config (`settings.map_run_id`, default newest run in `sf_window_meta`) and max `window_start`, per request — no legacy pointer, no `api/ibp.py`.
* Add the small response models (`MapMeta`, `ConstraintGeo`, `SpExposure`/`ExposuresResponse`, `ConstraintReach`) and pytest coverage; `pytest` green.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `serving-and-display-design.md` Phase 1; spec of record is `spec-phase1-serve-map.md` §3, §6, §7, §8.3. Runs against the DB populated by `0003-map-compute` (do that branch first — spec §8 "compute + API first").
* Queries are indexed slices (`WHERE run_id=? AND window_start=? AND settlement_point=? ORDER BY abs(sf) DESC LIMIT k` + its transpose) — sub-ms, no per-hour dimension: the SF structure is fixed per refit, so the explorer is **not** time-indexed.
* Identifiability guardrail (spec §6, non-negotiable): lead with the stable unsigned magnitude (`max_abs_sf` per constraint, `max_c|SF|` per node); signed per-constraint exposures are the caveated detail and must always ship with their window `sf_stability`/`oos_r2`.
* Run resolution is config-owned, resolved per request so a re-persist of the same `run_id` is picked up without redeploy; sweep run_ids are ignored.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `api/` — new `api/map.py` (router), `api/models.py` (new models), `api/main.py` (include router), `api/config.py` + `shared/settings.py` (`map_run_id`), `api/tests/test_map.py`.
* **Run/window resolution:** `settings.map_run_id` defaults to the newest `run_id` in `sf_window_meta`; current refit = `max(window_start)` for that run, resolved per request. Add a small resolver helper; do NOT read `implied_binding_proximity_current`, add `--promote`, or import `api/ibp.py` (deleted in 0001 / legacy).
* **Endpoints** (all `GET`, JSON):
  * `/map/meta` → latest-window row from `sf_window_meta`: `run_id, window_start, window_end, fit_r2, oos_r2, coverage, sf_stability, n_kept`.
  * `/map/constraints` → all `constraint_geo` rows for the latest window: `constraint_key, lat, lon, zone_shares, kv_*, spread_km, max_abs_sf, binding_hours` (the overlay layer).
  * `/map/exposures?sp&k` → `implied_shift_factors ⋈ constraint_geo` for that SP, top-k by `abs(sf)`: signed `sf`, centroid, `max_abs_sf`, `binding_hours` (the node-explorer click).
  * `/map/reach?constraint&k` → `implied_shift_factors ⋈` geocoded SPs for that constraint, top-k by `abs(sf)`: signed `sf`, sign split (import/export ends) + the constraint's centroid (the constraint click).
* **Models** in `api/models.py`: `MapMeta`, `ConstraintGeo`, `SpExposure` / `ExposuresResponse`, `ConstraintReach` — all small. Keep the existing soft-fail contract (404 = nothing served; 503 = window not built → client renders available pane alone).
* **Config:** add `map_run_id: str | None` to `shared/settings.py` (default resolves at query time), re-export via `api/config.py` in the module's existing style.
* Do NOT touch: `web/`; `compute/` (owned by 0003); `/ercot_state_range` / `/ercot_spp_range` / `/meta` (kept as-is — the map's node coloring stays realized congestion from Phase 0). Do NOT add any `/forecast/*` or a node-value layer (Phase 2).

## Commits

<!-- Grouped so the app imports and pytest is green at branch end. -->

* **Commit A — `feat(api): add /map response models`**
  * `api/models.py` — `MapMeta`, `ConstraintGeo`, `SpExposure`/`ExposuresResponse`, `ConstraintReach`.
* **Commit B — `feat(api): serve /map/* endpoints with per-request run/window resolution`**
  * `shared/settings.py` + `api/config.py` — `map_run_id`.
  * `api/map.py` — router with the run/window resolver + the four endpoints (indexed slice queries + transpose).
  * `api/main.py` — `include_router(map...)`; update URL comment (same commit so `main.py` never imports a missing module).
* **Commit C — `test(api): /map endpoint + openapi coverage`**
  * `api/tests/test_map.py` — meta returns a real current window w/ non-null `fit_r2`; **exposure/reach are transposes** (`sp=X` lists `c` ⇔ `constraint=c` lists `X` with the same `sf`, spec §7); run resolution reports `map-v1` and its latest window, no legacy path reachable.
  * `api/tests/test_openapi.py` — assert the new `Map*` schemas present.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `/map/meta` returns the configured `map-v1` run + its latest `window_start` (2025-11-04) with non-null `fit_r2` (0.992); `oos_r2` (0.790) / `coverage` (0.941) / `sf_stability` (0.563) present (`test_meta_reports_configured_run`, integration — **passing** now the 0003 Commit D backfill populated the served window).
* [x] `/map/constraints` returns every latest-window constraint with lat/lon/zone/kv/`spread_km`/`max_abs_sf`/`binding_hours` (`test_constraints_overlay_shape`; live rows served, exercised by the transpose test).
* [x] Exposure/reach transpose holds: `sp` in `/map/exposures?sp=X` lists `c` ⇔ `X` appears in `/map/reach?constraint=c` with the same `sf` (`test_exposure_reach_transpose`, integration — **passing against live `map-v1`**).
* [x] No legacy run or binding-proximity path is reachable via `/map/*`; run/window resolved per request (`test_resolution_defaults_to_newest_run`; router reads only `sf_window_meta`/`constraint_geo`/`implied_shift_factors`, no `ibp`/`--promote`/pointer).
* [x] `/openapi.json` includes the `Map*` schemas (`test_openapi_includes_map_schemas`); `pytest` green across `api/tests/` (**16 passed, 2 skipped** default; **18 passed** with `RUN_INTEGRATION=1`).

## Out of scope (stretch — spec §5)

* `/map/realized_drivers?ts&sp` (realized-μ decomposition: current SF ⋈ realized `M` for one hour) is the same slice math as Phase 2's `/forecast/drivers` with realized μ. Add here **only if cheap**; otherwise defer to Phase 2 and reuse that machinery. If added, label it "realized decomposition," never "forecast" (it is the oracle).
