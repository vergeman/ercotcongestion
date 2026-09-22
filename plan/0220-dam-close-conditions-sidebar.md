# 0220 - dam-close-conditions-sidebar

Type: fix
Branch: fix/0220-dam-close-conditions-sidebar

## Goal

* Show one frozen, DAM-close-safe Conditions snapshot, with identical MW values in every Map view.
* Read Load, Wind, Solar, and fuel-outage values from the latest ERCOT publication available at 10:00 CT on D-1 for the displayed delivery hour.
* Remove retrospective actual conditions from the Map sidebar so Forecast and ERCOT differ only in their congestion/price layer.

## Context

* The Map contains DAM prices only; it does not show real-time delivery pricing.
* The model already reads load/wind/solar at the legal D-1 10:00 CT cutoff via `compute.mu_forecast.panel.availability.dam_close_expr`; fuel outages already use the D-1 snapshot rule.
* `/conditions_range` instead uses `posted_datetime <= interval_ts` and returns actuals; Market/Compare then prefer those actuals. A later ERCOT forecast or realized delivery value can therefore appear beside a DAM price even though it was not available at DAM close.
* The canonical vintaged forecast tables and `resource_outages` data already exist. No backfill, ingest, migration, or pricing change is required.

## Approach

### Commit 1 — Return DAM-close Conditions only

* Work in: `api/services/conditions.py`, `api/schemas/conditions.py`, and `api/tests/test_conditions.py`.
* Entry point / primary change: make `conditions_range()` expose a single `dam_close_mw` value for each load zone, generation region, and outage fuel.
* Replace the Load/Wind/Solar forecast predicates with the same per-delivery-hour D-1 10:00 CT cutoff used by the μ forecast panel (`posted_datetime <= dam_close_expr(interval_ts)`), selecting the latest eligible vintage per interval and DST occurrence. Do not use `posted_datetime <= interval_ts`.
* Retain the outage forecast rule: select the newest daily outage snapshot posted on or before D-1 and sum units expected to remain out at the displayed hour according to `planned_end_date`.
* Stop querying `load_by_zone`, `wind_hourly_regional`, and `solar_hourly_regional`; do not calculate or return delivered actual load, generation, or active-outage values from this endpoint.
* Rename the response fields from `forecast_mw`/`actual_mw` to `dam_close_mw` in the Pydantic schema and API contract. The neutral name covers both projected load/generation and an outage already reported as active at DAM close but expected to continue into delivery. Preserve the dense hourly response, source-specific empty lists, and existing 503 behavior.
* Add focused query/response tests proving: (a) a post-DAM-close but pre-delivery forecast is excluded, (b) the latest eligible pre-close vintage wins, (c) D-1 outages and planned end dates are applied, including an outage already active at DAM close, (d) no actual-series query is issued, and (e) a missing DAM-close value produces null/empty Conditions data rather than an actual fallback.
* Do NOT touch: forecast-model feature reads, forecast publication, DAM SPP/shadow/λ ingest, actual-series ingest tables, or any database migration.

### Commit 2 — Make every Map view display the same DAM-close snapshot

* Work in: `web/src/api/types/map.ts`, `web/src/components/panels/SidePanel.tsx`, API-client tests/types affected by the contract, and focused Map/sidebar tests if present.
* Entry point / primary change: replace the per-view `conditionValue()` / `regionMw()` selection with one accessor for `dam_close_mw`; use the identical response field for Forecast, ERCOT/Market, Compare, and Error alike. The UI must not issue a second, view-specific Conditions query.
* Remove the Market/Compare actual-preference and forecast-fallback behavior. Conditions must no longer change when the Map view changes.
* Remove every row-level `(Forecast)` suffix and do not append `Forecast` to the Load, Wind, Solar, or Outages group labels: all Conditions values now have the same provenance.
* Wrap the `Conditions` section header in the existing `Tooltip` component. On hover/focus, explain that the values are load/generation forecasts plus reported outage expectations available before the D-1 10:00 CT DAM close; an outage can already be active at that time but its delivery-hour continuation remains an expectation. State that the snapshot is shared across Map views, is not delivered actuals, and is not claimed to be the exact internal ERCOT clearing-engine input. Retain `Outages by Fuel`'s clarification that it is unavailable MW rather than generation.
* Keep the Map view labels and all nodal pricing behavior unchanged: Forecast remains the project congestion forecast, while ERCOT/Market remains published DAM SPP/λ/congestion.
* Verify cursor movement, expanded regional rows, missing-value rendering, number formatting, and mobile/sidebar variants continue to work without a view-dependent Conditions value.
* Do NOT touch: the Forecast/Market/Compare/Error map rendering, `forecast_range`/`ercot_range` payloads, scoring/Brief UI, or real-time/SCED views.

### Commit 3 — Document the Conditions provenance

* Work in: `api/ROUTE_INVENTORY.md`, the relevant Map-facing copy/comments, and `plan/0141-load-generation-region-panels.md` only if this repository treats completed plans as corrected historical design documentation.
* State that Conditions is a D-1 10:00 CT snapshot shared across Map views; it is contextual information available at DAM close, not delivered actuals and not real-time pricing.
* State separately that actual Load/Wind/Solar and actual outage status remain ingested data for offline analysis/model evaluation, but are intentionally out of scope for this DAM-only Map sidebar.
* Do NOT alter ingest documentation that describes actual-table retention or the model's forecast evaluation process.

## Acceptance

* [ ] For every displayed delivery hour, Load/Wind/Solar uses the latest forecast published no later than D-1 10:00 CT; forecasts published after DAM close never appear.
* [ ] Fuel outage values use the D-1 expected-outage snapshot and planned-end logic; they are not active-at-delivery actual outages.
* [ ] Forecast, ERCOT/Market, Compare, and Error read the same `dam_close_mw` payload and show byte-for-byte identical formatted Conditions MW values at the same cursor hour; a view toggle alone cannot issue a Conditions request or change a Conditions value.
* [ ] `/conditions_range` does not read actual load/generation tables or return actual condition fields.
* [ ] No individual Conditions row carries a `Forecast` suffix. The accessible Conditions-header tooltip explains the shared DAM-close provenance, including the forecast/known-outage distinction, preserves existing numeric formatting and missing-value behavior, and does not imply real-time prices or delivered quantities.
* [ ] Focused API tests and web typecheck/lint pass without database migration, backfill, or ingest changes.
