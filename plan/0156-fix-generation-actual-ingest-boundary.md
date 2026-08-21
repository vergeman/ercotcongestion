# 0156 - fix-generation-actual-ingest-boundary

Type: fix
Branch: fix/0156-generation-actual-ingest-boundary

## Goal

* Keep rolling wind/solar actual generation refreshed through the full Central-time delivery day.
* Backfill every affected wind/solar actual hour from a settled next-morning report vintage.
* Make the Daily Brief and Conditions Market/Compare/Error surfaces show repaired actuals without changing forecast-model inputs.

## Context

* The 15-minute live poll formats `deliveryDate` from UTC dates; ERCOT interprets it as a Central-time delivery date.
* After 19:00 CDT / 18:00 CST, the final refresh of the prior delivery day is too early; HE20–24 retain null `gen_*` values while forecast values remain present.
* `wind_hourly_regional` / `solar_hourly_regional` feed Conditions actuals and Brief actual net load only; model covariates read the separate DAM-close forecast tables.

## Approach

* Work in: `ercot_ingest/backfill.py`, `ercot_ingest/live_updater.py`, and ingest tests.
* Add a Central-time delivery-date-range helper for the live rolling wind/solar fetch: derive the inclusive dates from `[start, end)` in `America/Chicago`, including the prior date at the 19:00/18:00 UTC crossover. Keep the existing UTC-labelled daily/backfill semantics for load, DAM, and other date endpoints.
* Pass that explicit Central delivery-date range only to the live wind/solar path; retain the two-hour Central posting-time window and newest-vintage upsert behavior.
* Add regression tests for CDT and CST evening boundaries, exact local midnight, and a normal daytime window; assert the requested `deliveryDateFrom`/`deliveryDateTo` remain on the correct delivery date.
* Inventory production rows whose wind or solar `gen_system_wide` is null after a delivery hour has settled; replay only those delivery dates with `backfill.py --endpoint wind` and `--endpoint solar` using `settled_posting_window`, without `--resume` so existing ingest-log entries do not suppress repair.
* Verify the replay fills system and regional `gen_*` fields for all ordinary hours, preserves forecast tables/vintages, and records the backfill range and row counts in the operational handoff.
* Exercise `GET /conditions_range` over repaired dates and the map’s Market, Compare, and Error modes; verify Market/Compare receive actual generation and Error continues to compute against its existing forecast side.
* Exercise the on-demand Brief hero for a repaired day; verify `actual_net_load` is calculated from populated wind/solar actuals. No artifact regeneration is required because the hero reads these tables on demand.
* Do NOT touch: `compute/mu/features.py`, DAM-close forecast ingest, model fitting, or forecast artifacts.

## Acceptance

* [ ] Deploy the live-ingest fix, then verify a post-19:00 CDT / post-18:00 CST production poll continues to refresh the prior Central delivery date.
* [x] Regression tests cover both DST offsets, local midnight, and a normal daytime window; UTC-labelled date endpoints retain their existing behavior.
* [x] Production replayed Jul 18 and Jul 20–Aug 18; the post-repair inventory has no missing settled wind/solar `gen_system_wide` rows in that range.
* [x] Conditions serves repaired Market actuals; Compare uses those actuals, Error retains its forecast side, and the Daily Brief reads repaired `actual_net_load` without changing model inputs.
