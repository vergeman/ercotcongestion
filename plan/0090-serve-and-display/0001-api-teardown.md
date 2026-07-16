# 0090.0001 - api-teardown

Type: refactor
Branch: refactor/0001-api-teardown

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Rewrite `/topology` to return geocoded settlement points only — no synthetic buses/lines.
* Delete the synthetic-grid serving routes (`/state`, `/validation`, `/ptdf`, `/ibp`) and their models/tests.
* Leave the kept endpoints (`/ercot_state_range`, `/ercot_spp_range`, `/meta`) working and `pytest` green.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `serving-and-display-design.md` Phase 0; spec of record is `spec-phase0-teardown.md` §2–§4, §6–§8.
* The API and web change are coupled, but the API half is self-contained and testable in isolation — do it first (spec §7), web (`0002-web-teardown`) lands against the already-repointed API.
* Deletions are verified safe: no kept module imports the deleted symbols; `ercot_state`/`meta` read `scorecard.json` as a *file* (not via the deleted `Scorecard*` models or `/validation`), and `meta` reads the legacy IBP pointer via raw SQL, not `api/ibp.py` (spec §2.3).
* `/ercot_state_range` stays entangled with the served legacy run (`congestion_matrices.npz` + `scorecard.json` `params.ref`) — kept working as-is; re-sourcing is deferred to serving-plan §4.3, NOT this branch (spec §4).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `api/` (routes, `api/models.py`, `api/main.py`, `api/services/`, `api/tests/`).
* Adopt design decision (A): the compare chassis survives; only its data sources change. No single-map collapse.
* `/topology` rewrite in `api/services/topology_builder.py`: keep `_sp_load_zone_from_name`, the disk-cache + atomic-write scaffold, `get_or_build_topology(force)`, and the `__main__` block; delete the `import pypsa` network load, `_buses_feature_collection`, `_lines_feature_collection`, `_load_bus_cluster_labels`, `_load_sp_cluster_labels`, `_load_zone_polygons`, `_cluster_labels_key`, and cluster-keyed cache invalidation. New shape: `build_topology() -> {'settlement_points': _settlement_points_feature_collection()}`.
* SP feature `properties`: `sp_id`, `sp_type`, `load_zone`, `capacity_mw` (from `matched_capacity_mw`); DROP `cluster_id`/`best_corr`. `_cache_is_current`: stale if the cache carries `buses`/`lines` or its SP features lack `capacity_mw` → legacy cache auto-rebuilds on first hit.
* `api/topology.py`: change docstring/description only — still returns `JSONResponse` with the 24 h `Cache-Control`.
* `api/main.py`: drop `state, validation, ptdf, ibp` from the import line and their four `include_router(...)` calls; update the URL comment.
* `api/models.py`: delete the models listed in spec §2.2 (incl. the unused `TopologyResponse` and the `IbpErcot*` set); KEEP `ErcotSpState`/`ErcotStateRange*`, `ErcotSpSpp`/`ErcotSppRange*`, `MetaResponse`.
* Config (spec §2.5): trimming `NETWORK_NC`, `BUS_WEATHER_LOAD_ZONES_CSV`, `GENERATOR_MATCHES_ENRICHED_CSV` in `api/config.py` is optional/low-value — do it in this branch or leave it, not a follow-up.
* Do NOT touch: `web/`; `api/ercot_state.py`, `api/ercot_spp.py`, `api/meta.py` (kept working); `compute/` OPF/synthetic machinery + promote/symlink/clustering (out of scope, design §8); do NOT re-source `/ercot_state_range` off the legacy run (spec §4, deferred).

## Commits

<!-- Grouped so each commit leaves the tree importable; pytest green at branch end. -->

* **Commit A — `refactor(api): rewrite /topology builder to settlement-points only`**
  * `api/services/topology_builder.py` — deletions around `_settlement_points_feature_collection`; new `build_topology()`; SP `properties` = `sp_id/sp_type/load_zone/capacity_mw`; `_cache_is_current` legacy-schema staleness.
  * `api/topology.py` — docstring/description only.
  * `api/tests/test_topology.py` — rewrite: assert payload is `settlement_points`-only (~1,092 features), each with `sp_id/sp_type/load_zone/capacity_mw`, no `buses`/`lines`; a stale legacy cache rebuilds.
* **Commit B — `chore(api): delete synthetic serving routes (state/validation/ptdf/ibp)`**
  * `git rm` `api/state.py`, `api/validation.py`, `api/ptdf.py`, `api/services/ptdf_service.py`, `api/ibp.py`.
  * `api/main.py` — drop the four imports + `include_router(...)` calls; update URL comment (same commit so `main.py` never imports a deleted module).
  * `git rm` `api/tests/test_state.py`, `api/tests/test_validation.py`, `api/tests/test_integration.py`, `api/tests/test_ibp.py`.
* **Commit C — `chore(api): trim orphaned models + openapi test (+ config)`**
  * `api/models.py` — delete the spec §2.2 model set (incl. unused `TopologyResponse`, `IbpErcot*`); keep the Ercot*/`MetaResponse` set.
  * `api/tests/test_openapi.py` — rewrite: assert deleted schemas (incl. `IbpErcot*`) are ABSENT and `ErcotStateRangeResponse`/`MetaResponse` PRESENT.
  * `api/config.py` — optional trim of the three now-unused paths.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `api/main.py` imports and the app loads with `state`/`validation`/`ptdf`/`ibp` routers gone.
* [x] `GET /topology` returns `settlement_points` only (1,092 features) with `sp_id/sp_type/load_zone/capacity_mw`, no `buses`/`lines`; a stale legacy cache auto-rebuilds on first hit.
* [x] `/openapi.json` omits the deleted schemas (incl. `IbpErcot*`) and includes `ErcotStateRangeResponse` + `MetaResponse`; `test_openapi.py` asserts both.
* [x] `test_meta.py` passes; `/ercot_state_range` and `/ercot_spp_range` still return realized data.
* [x] `pytest` green across `api/tests/` (9 passed; deleted test files gone, `test_topology.py`/`test_openapi.py` rewritten).
