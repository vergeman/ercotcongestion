# 0001 - api-contracts

Type: refactor
Branch: refactor/0160-frontend-api-architecture-refactor/0001-api-contracts
Base: `main`
Source: `plan/0160-frontend-api-architecture-refactor/README.md`

## Goal

* Classify every read route as bootstrap, interaction, primitive, compatibility, or removable.
* Consolidate duplicate realized-range routes without breaking external clients.
* Make resource availability and query parameter names consistent across web-facing APIs.

## Context

* `/map/summary`, `/scoreboard/summary`, and `/analysis/brief` already consolidate cold-load fan-out.
* `/ercot_state_range` and `/ercot_spp_range` remain mounted, but the current web app uses `/ercot_range`.
* Brief routes mix `day`/`delivery_date` and `run`/`run_id`; availability is represented inconsistently by 503, 404, `null`, and response unions.

## Approach

* Work in: `api/main.py`, `api/{analysis,map,scoreboard,ercot_range,ercot_state,ercot_spp,forecast,conditions}.py`, `api/models.py`, `api/tests/test_openapi.py`.
* Produce a route-consumer inventory, including non-web consumers, before altering or removing mounted endpoints.
* Declare composite routes bootstrap read models; retain their independently unavailable sections as explicit typed fields with provenance/status rather than implicit endpoint-specific `null` semantics.
* Design a backwards-compatible migration from `/ercot_state_range` and `/ercot_spp_range` to `/ercot_range`; advertise deprecation, update consumers, observe use, then remove on a scheduled version boundary.
* Normalize new analysis/brief APIs on `delivery_date` and `run_id`; accept legacy aliases only during the migration and document them in OpenAPI.
* Keep `/map/exposures`, `/map/reach`, and `/map/constraints/ranked` as independent interaction resources. Do NOT append them to `/map/summary`.
* Ship additive aliases, response fields, and deprecation metadata only; do not require a coordinated web deployment or remove a live route in this branch.

## Acceptance

* [x] Every mounted web route has an ownership classification and known consumer list.
* [x] The OpenAPI schema documents bootstrap partial availability and all supported parameter aliases.
* [x] Existing and migrated realized-range clients receive equivalent data and error semantics.
* [x] No endpoint is removed until its external-consumer deprecation window has completed.
* [x] API tests and the deployed web build remain compatible with both old and new request forms.
