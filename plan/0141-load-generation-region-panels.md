# 0141 - load-generation-region-panels

Type: feat
Branch: feat/0141-load-generation-region-panels

## Goal

* Add a **Conditions** section to the map's Stats tab: Load by Region (8
  weather zones + system), Wind Generation (5 regions + system), Solar
  Generation (6 regions + system), Outages by Fuel (NP1-346, 6 fuels +
  total).
* Each category is one caret row (name + aggregate value) that expands to
  its per-region/per-fuel breakdown. One section, one border; no dividers
  between the four rows, no intermediate "System"/"Total" child row.
* Values move with the existing timeline cursor and switch forecast/actual
  per the map's Forecast/Market/Compare/Error toggle. Numbers only — no
  sparkline, no p10/p90, no Δ column.
* One backend endpoint, `GET /conditions_range`, serves all four.
* Network section's old "Total Load" stat is removed (superseded by
  Conditions' Load by Region row, which also has a forecast side it didn't).

## Context

* Ported from `docs/daily_brief_v6_prototype.html`'s Conditions panel
  (`renderB()`), which the prototype itself flags for this move.
* Region data already ingested at 15-min/hourly cadence:
  * Load — actual `load_by_zone` (NP6-345-CD), forecast `load_forecast_zonal`
    (NP3-561-CD, vintaged).
  * Wind/Solar — actual `wind_hourly_regional`/`solar_hourly_regional`
    (NP4-732/737-CD), forecast `wind_forecast_regional`/
    `solar_forecast_regional` (vintaged).
* Forecast side always reads the vintaged tables at `posted_datetime <=
  interval_ts` (no lookahead) — never the actual tables' own STWPF/STPPF
  columns, which dedup to the most recent posting (~49h lag, migration
  `26_dam_close_forecasts.sql`) and aren't knowable ahead of time.
* True generation-by-fuel (gas/coal/nuclear/hydro MW produced) doesn't exist
  in this project's ingestion — ERCOT's Fuel Mix Report ships as yearly
  Excel files, not the MIS report API used elsewhere, and is system-wide
  only. Skipped; would need its own ingestion module.
* `resource_outages`/NP1-346 (migration 27) is a *different* quantity — MW
  currently offline, not produced — and a different cadence: one D-vintage
  snapshot per day, not hourly. Reuses `compute/mu/outage_exposure.py`'s
  (plan/0089) leak-safe vintage rule: forecast = newest `posted_date <= D-1`
  summed over `planned_end_date`-covered events; actual = newest
  `posted_date <= D` summed over events active at the hour. Fuel buckets
  extend `outage_exposure.FUEL_BUCKETS` (gas/wind/solar) with coal and
  hydro split out of "other" for display only.
* Three regionalizations (weather zones, wind regions, solar regions) don't
  crosswalk to each other or to the map's settlement `load_zone`. Each
  renders in its own native geography — no pivot.
* **API shape**: started as three endpoints (load/generation/outages), each
  already bundling `forecast_mw`+`actual_mw` per row since a Conditions row
  needs both sides at once (unlike per-SP congestion's `/ercot_range` +
  `/forecast_range` split, which only exists because two separate map panes
  render independently). Once the UI became one section, the three merged
  into `/conditions_range` for the same reason — one section, one request.
  Stayed its own endpoint rather than folding into `/ercot_range`/
  `/forecast_range`: those are per-SP (~1,100/hour, a heavy hot path),
  Conditions is per-region/fuel aggregates — different granularity.
  `total_load_mw` dropped from `/ercot_range`/`/ercot_spp_range` as
  redundant (Conditions' Load system row is strictly more, forecast+actual);
  the Network "Total Load" stat was removed rather than re-pointed, per
  direction to rely on Conditions instead.

## Approach

### Backend

* `api/conditions.py` (new) — `GET /conditions_range?start&end`. Four
  pieces: Load (`load_by_zone` + `load_forecast_zonal`), Wind, Solar (same
  actual/forecast pairing), Outages (`resource_outages`, padded 3 days back
  for D-1 vintage resolution, `bisect` per hour). Dense hourly grid across
  `[start, end]` — a source with nothing for an hour contributes an empty
  list, not an error. 503 only when all four sources are empty.
* `api/models.py` — `ZoneLoad`/`RegionGen`/`FuelOutage`
  (`{key, forecast_mw, actual_mw}`), wrapped in `ConditionsEntry`/
  `ConditionsRangeResponse`.
* `api/ercot_range.py`, `api/ercot_spp.py` — dropped the `load_by_zone` JOIN
  and `total_load_mw` field.
* `api/main.py` — `conditions.router` replaces the three prior routers.
* Deleted `load_zone.py`/`generation.py`/`outages.py` + their tests; added
  `test_conditions.py`; updated `test_ercot_range.py`/`test_ercot_spp.py`.

### Frontend data

* `types.ts` — `ConditionsEntry`/`ConditionsRangeResponse`; dropped
  `total_load_mw` from `ErcotRangeEntry`/`ErcotSppRangeEntry`.
* `client.ts` — single `fetchConditionsRange`, same optional-window/
  503→null contract as `fetchForecastRange`.
* `prefetch.ts` — one `conditionsCache`/`ingestConditionsRange`/
  `getConditionsCached`, fetched in `prefetchWindow`'s existing
  `Promise.all`.

### Frontend UI

* `MapWorkspace.tsx` — one `conditionsStats` memo off
  `timestamps[currentIndex]`; `networkStats` no longer computes
  `totalLoadMw`.
* `SidePanel.tsx` — one "Conditions" `np-section`, four `ExpandableGroup`
  rows ("Load by Region", "Wind Generation", "Solar Generation", "Outages by
  Fuel"). Shared `regionMw(row, mapView)` (forecast on Forecast/Error,
  actual on Market/Compare) and `regionLabel(key)` (display-name exceptions,
  title-case fallback) across all four. Local `useState` per group tracks
  expand state.

## Acceptance

* [x] `GET /conditions_range` returns per-interval load/wind/solar/outages;
      503 on an empty window.
* [x] Forecast rows never lookahead: `posted_datetime <= interval_ts`
      (Load/Wind/Solar), `posted_date <= D-1` (Outages) — covered by tests.
* [x] Stats tab shows one Conditions section, four caret rows, no dividers,
      each collapsed by default and independently expandable.
* [x] Scrubbing moves every row; missing data shows "—". Outages changes
      only at day boundaries — by design.
* [x] View toggle (Forecast/Error vs. Market/Compare) switches every row's
      number.
* [x] Total Load gone from Network and from `/ercot_range`/`/ercot_spp_range`.
* [x] `tsc --noEmit` clean; API tests pass (3 pre-existing unrelated
      `test_analysis.py` failures throughout, confirmed via `git stash`).
