# 0141 - load-generation-region-panels

Type: feat
Branch: feat/0141-load-generation-region-panels

## Goal

* Add a **Load by Region** panel to the map's Stats side-panel tab: ERCOT's
  8 weather zones + system total, one labeled MW number per zone.
* Add a **Generation** panel to the same tab: wind broken out by its 5 native
  ERCOT regions + system total, and solar broken out by its 6 native regions +
  system total.
* Both panels move with the existing timeline scrubber (same per-hour cursor
  that drives Total Load / DAM System λ today) and switch each row's shown
  number between ERCOT's forecast and ERCOT's actual as the map's
  Forecast/Market/Compare/Error toggle changes.
* Numbers only — no whisker/sparkline, no p10/p90, no forecast-vs-actual Δ
  column (the prototype has all three; this port drops them).

## Context

* Ported from `docs/daily_brief_v6_prototype.html`'s Conditions panel (`#tb`,
  built by `renderB()`, prototype line ~1577), which the prototype's own
  in-page note already tags for this exact move: "It belongs with `Total
  Load` on the map's Stats tab" / "Natural home is beside `DAM System λ`".
* `SidePanel.tsx`'s Stats tab already has a `Network` section (Total Load,
  DAM System λ) computed in `MapWorkspace.tsx` (`networkStats`, ~line 446)
  from `timestamps[currentIndex]` — the same cursor the map scrubber drives.
  The new panels hook into that identical cursor via `api/prefetch.ts`'s
  existing per-window-cache pattern (`ercotSppCache`/`forecastCache` +
  `get*Cached(ts)`); no new time-sync mechanism is needed.
* All the region data is already ingested at 15-min/hourly cadence but **no
  endpoint exposes it** — only `load_by_zone.total` is selected today (by
  `/ercot_range` and `/ercot_spp_range`), never the 8 per-zone columns:
  * Load, actual — `load_by_zone` (NP6-345-CD), 8 weather zones + `total`.
  * Load, forecast — `load_forecast_zonal` (NP3-561-CD), vintaged on
    `(posted_datetime, interval_ts, dst_flag)`, same 8 zones + `system_total`.
  * Wind, actual — `wind_hourly_regional` (NP4-732-CD), 5 regions (Panhandle,
    Coastal, South, West, North) + system-wide `gen_*`.
  * Wind, forecast — `wind_forecast_regional`, vintaged, same 5 regions,
    `stwpf_*` (point forecast).
  * Solar, actual — `solar_hourly_regional` (NP4-737-CD), 6 regions
    (CenterWest, NorthWest, FarWest, FarEast, SouthEast, CenterEast) +
    system-wide `gen_*`.
  * Solar, forecast — `solar_forecast_regional`, vintaged, same 6 regions,
    `stppf_*`.
* `wind_hourly_regional`/`solar_hourly_regional`'s own forecast-looking
  columns (`stwpf_*`/`stppf_*`) are **not safe as a forecast source** —
  `db/migrations/26_dam_close_forecasts.sql` documents these tables dedup to
  the most recent posting (~49h after the hour, 0% knowable at DAM close).
  Forecast numbers must come from the vintaged `*_forecast_regional` /
  `load_forecast_zonal` tables instead, reading the latest posting with
  `posted_datetime <= interval_ts` (the same no-lookahead boundary that
  table's own CHECK constraint enforces) — never the migration-06 tables'
  point-forecast columns.
* No fuel-mix/genmix data is ingested anywhere in this project — "Generation"
  here means wind + solar, the only generation types this project has.
* Three regionalizations exist and none crosswalk to each other or to the
  settlement `load_zone` already on the map (weather zones vs. wind regions
  vs. solar regions). Show each dataset in its own native geography, no
  pivot/crosswalk — the prototype's own pivot table is flagged in its source
  comment as "a judgement, not a lookup" for conflating them, and the user
  explicitly wants the plain per-region numbers, not that pivot.

## Approach

### 1. Backend: two new range endpoints

* Work in: `api/`, mirroring `api/ercot_spp.py` (actual-side join) and
  `api/forecast.py` (vintaged-forecast selection + soft-fail contract).
* Add `api/load_zone.py`, `GET /load_zone_range?start&end`:
  * Actual: `DISTINCT ON (interval_ts) ... FROM load_by_zone ... ORDER BY
    interval_ts, dst_flag ASC` (collapse DST duplicates exactly like
    `ercot_spp.py`), the 8 zone columns + `total`→`"system"`.
  * Forecast: `DISTINCT ON (interval_ts) ... FROM load_forecast_zonal WHERE
    posted_datetime <= interval_ts ... ORDER BY interval_ts, dst_flag ASC,
    posted_datetime DESC` (latest no-lookahead vintage), same 8 zones +
    `system_total`→`"system"`.
  * `LEFT JOIN` the two by `interval_ts`; 503 when the window has no
    `load_by_zone` rows (matches the realized-range soft-fail contract).
* Add `api/generation.py`, `GET /generation_range?start&end`: same shape,
  two independent region groups in one response — wind (`wind_hourly_regional`
  actual / `wind_forecast_regional` forecast, 5 regions + system) and solar
  (`solar_hourly_regional` actual / `solar_forecast_regional` forecast, 6
  regions + system). 503 when the window has no `wind_hourly_regional` rows.
* Add to `api/models.py`: `ZoneLoad{zone:str, forecast_mw:float|None,
  actual_mw:float|None}`, `LoadZoneEntry{interval_ts, zones:list[ZoneLoad]}`,
  `LoadZoneRangeResponse{start,end,count,entries}`; `RegionGen{region:str,
  forecast_mw:float|None, actual_mw:float|None}`, `GenerationEntry{interval_ts,
  wind:list[RegionGen], solar:list[RegionGen]}`,
  `GenerationRangeResponse{start,end,count,entries}`.
* Register both routers in `api/main.py` (import + `include_router`, update
  the `# Routers mounted at root` URL comment).
* Add `api/tests/test_load_zone.py`, `api/tests/test_generation.py` mirroring
  `test_ercot_spp.py`/`test_forecast.py`'s fixtures: response shape, 503 on an
  empty window, and a case proving no returned forecast row has
  `posted_datetime > interval_ts`.

### 2. Frontend data plumbing

* Work in: `web/src/api/types.ts`, `web/src/api/client.ts`,
  `web/src/api/prefetch.ts`.
* `types.ts`: TS mirrors of the new Pydantic models (`ZoneLoad`,
  `LoadZoneEntry`, `LoadZoneRangeResponse`, `RegionGen`, `GenerationEntry`,
  `GenerationRangeResponse`).
* `client.ts`: `fetchLoadZoneRange(start?, end?)` /
  `fetchGenerationRange(start?, end?)`, copying `fetchForecastRange`'s
  optional-window query-string + `503 → null` + `!r.ok → throw` pattern.
* `prefetch.ts`: add `loadZoneCache`/`generationCache` (keyed the same way as
  `ercotSppCache`, via `roundToInterval`/`cacheKey`), `ingestLoadZoneRange`/
  `ingestGenerationRange`, `getLoadZoneCached(ts)`/`getGenerationCached(ts)`
  accessors, and clear both in `clearCache()`. Fetch both range calls in
  `prefetchWindow`'s existing `Promise.all` (both the explicit-window and the
  default-landing branches) alongside `fetchErcotRange`/`fetchForecastRange` —
  same soft-fail contract, a 503 just leaves that cache empty.

### 3. Frontend UI: the two Stats-tab panels

* Work in: `web/src/workspaces/MapWorkspace.tsx`,
  `web/src/components/panels/SidePanel.tsx`.
* `MapWorkspace.tsx`: add `loadZoneStats`/`generationStats` `useMemo`s next to
  `networkStats` (~line 446), reading `getLoadZoneCached(cur)`/
  `getGenerationCached(cur)` off the same `cur = timestamps[currentIndex]`.
  Add `loadZone: loadZoneStats, generation: generationStats, mapView:
  renderedView` to `sidePanelProps` (~line 1130).
* `SidePanel.tsx`: accept the three new props; render two new `np-section`s
  directly below the existing `Network` section, in the `tab === "stats"`
  branch only:
  * **Load by Region** — one `Stat` row per weather zone (8 zones, order from
    `compute/ercot/zones.py`'s `WEATHER_ZONES`, then `System`), with a small
    display-name map for the underscored keys (`far_west`→"Far West",
    `north_central`→"North Central", `south_central`→"South Central") and
    plain title-case for the rest.
  * **Generation** — two sub-groups, Wind (5 regions + System) and Solar (6
    regions + System), one `Stat` row per region, with a display-name map
    copied from the prototype's own `PRETTY` object for the non-underscored
    names (`farwest`→"Far West", `fareast`→"Far East", `centerwest`→"Center
    West", `centereast`→"Center East", `northwest`→"Northwest",
    `southeast`→"Southeast"; `panhandle`/`coastal`/`south`/`west`/`north` need
    only title-case).
  * Value shown per row: `mapView === "forecast" || mapView === "error" ?
    forecast_mw : actual_mw` — one number per row, reusing `Stat`'s existing
    `—` null rendering as-is. No new toggle state; this reads the `view` axis
    MapWorkspace already owns.
* Do NOT touch: `web/src/components/map/*`, the Constraints/Scorecard tabs,
  the existing `NetworkStats` Total Load / DAM λ stats (left as-is — additive,
  not a replacement), any zone/region crosswalk logic, URL/link params.

## Acceptance

* [ ] `GET /load_zone_range` and `GET /generation_range` return per-interval
      region rows for a known-good historical window; both 503 on an empty
      window.
* [ ] Every forecast row served has `posted_datetime <= interval_ts` —
      covered by a test.
* [ ] Map Stats tab shows "Load by Region" (8 zones + System) and
      "Generation" (Wind: 5 regions + System; Solar: 6 regions + System)
      below Network.
* [ ] Scrubbing the timeline moves both panels' values; an hour with no
      ingested regional data shows "—" per row rather than erroring.
* [ ] Toggling the map View between Forecast/Error and Market/Compare
      switches every row's shown number between forecast and actual.
* [ ] `tsc --noEmit -p web/tsconfig.app.json` clean; new API tests pass.
