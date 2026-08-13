# 0129 - build the v6 daily brief

Turn `docs/daily_brief_v6_prototype.html` into the served product.

The prototype's own **Data status** table (`render5`) is the authoritative gap list;
this index sequences it. Statuses below are quoted from that table.

## Scope

v6 **replaces the Analysis page entirely and becomes the front page.** It is not a
fourth view alongside Map / Matrix / Analysis — it is the entry point, and the Map
becomes something the brief links *into*.

Consequences that shape every sub-plan below:

* `/` routes to the brief. `web/src/main.tsx` currently sends both `/` and every
  unknown path to `<App />` (the Map) via `path="*"`; that catch-all has to be
  re-pointed deliberately, not left to fall through.
* `web/src/pages/BriefPage.tsx` is the new entry-point surface. Keep the
  1,567-line `AnalysisPage.tsx` legacy blob reader on `/analysis` until `0012`;
  its panels are re-sourced into BriefPage rather than refactored in place.
* The **`PlaybackScrubber` timeline comes off the brief page** — an hour cursor is the
  wrong control for a page whose unit is a delivery day. **The URL coordinate it reads
  must survive intact** (`0009`); the brief has to keep emitting a well-formed
  `?t/?ws/?we` so it can hand one to the Map.
* Everything the old page uniquely fed becomes dead code once the panels land —
  `analysis_brief`, `build_brief`, and most of `compute/analysis/`. Torn down in
  `0012`, after nothing reads it, per the `0094` pattern.
* The reader we are designing the top of the page for **does not know what a shadow
  price is.** The hero text and the map link are what they get; everything below the
  hero is for the reader who already stayed. That is the reason `0011` exists.

## The architectural pivot (read first)

v6 does not fit the `analysis_brief` blob. The blob is precomputed and truncated at
build time — top-5 nodes per constraint (249 of ~5,800 SF cells), 33 of 1,024
constraints above the `floor_abs $2` serving floor — and every "partial" row in the
data-status table traces to that truncation. The prototype says so directly about the
below-floor gap: *"expected to fall out of the rebuild as a query filter rather than a
payload change."*

So the rebuild is a shift **from one precomputed JSONB document to a set of query
endpoints** reading `forecast_sf_artifact` + the DAM tables directly. `0002` and `0003`
are both instances of that move; they are the pattern, not exceptions to it.

`analysis_brief` and `build_brief` stay untouched and keep serving the existing
`/analysis` page until the v6 panels replace it panel by panel. Do not widen them, and
do not delete them mid-flight — `0012` is the teardown, and it runs last.

## Correction to the data-status table

It lists **history of past FORECASTS** as `mock` — *"nothing persists what was forecast
for a past delivery day."* That is wrong as stated: `forecast_sf_artifact` persists
`E_mu` (hours × constraints, forecast μ, untruncated) per delivery day, which is what
`compute/jobs/daily_brief.py::_load_artifact` already loads. Past forecasts are
therefore **recoverable by rollup over existing artifacts**, not lost. This is a
backfillable derived view (`0004`), not an urgent capture — it does not need to be
sequenced first to stop the bleeding, because there is no bleeding.

## Order

**Phase 0 — cheap, independent, unblocks correctness in the Context panel.**

1. `0001-ingest-guards` — purge the NaN `gen_*` rows already in `wind_hourly_regional`
   (three DST spring-forward days) and pin a regression test. **The ingest guard already
   exists** — `loaders.py::_f` coerces NaN to `None` and every `gen_*` routes through
   it — so this is a repair of rows written before that fix, not a new guard. NaN makes
   every comparison false, so a percentile over an affected series is silently wrong.
   Also unstall `load_by_zone` (stops 2026-07-22) and refresh `constraint_geo`
   (stamped 2025-12-13).

**Phase 1 — the two foundations. Neither blocks the other; both are unblocked today.**

2. `0002-hero-generator` — **recommended first.** Builds
   `compute/analysis/hero_window.py`, the trailing-30-day query layer over
   `ercot_dam_shadow_prices` and `ercot_dam_spp − dam_system_lambda`. Four other panels
   read that same layer (Standouts, the 30-day column on Top Constraints, Chronic
   elements, the board track), and nothing else in the repo builds it. It is also the
   most-wrong part of the page today: the hero restates a spread axis off `D.regimes[0]`,
   which exists nowhere in `compute/`.

3. `0003-brief-node-rows` — routes the untruncated SF column per settlement
   point and per pair as `/analysis/node` and `/analysis/path`. `node_drivers`
   (`compute/sf/project.py:233`) and `pair_contributions`
   (`compute/analysis/brief.py:56`) are already written and never routed, so the cost is
   low against what it unblocks: driver attribution, driver share and counterparties on
   Top Nodal Congestion; the whole Node↔node paths panel; the node row of Forecast Grade
   (`NODES_GRADEABLE`); and the Standouts materiality gate, which currently stands in
   with μ-hours until `Σ|SF·μ|` is servable.

   *The alternative ordering is `0003` before `0002`*, and it is defensible — Standouts is the
   heart of the page and the hero is a summary of it. Take it if node attribution
   matters more than the top of the page. The reason not to: `0002`'s exception tiering
   computes from the trailing window and does not need SF, so `0003` improves the gate
   rather than enabling it, while `0002`'s window layer has no substitute.

**Phase 2 — panels that depend on Phase 1.**

4. `0004-forecast-history-rollup` — daily forecast Σμ per constraint, rolled up
   from `forecast_sf_artifact.E_mu` across delivery days. Lets Standouts rank today's
   forecast against a window of past **forecasts** instead of past settles, and removes
   the `basis: cast_keys` workaround from `0002`'s magnitude slot. Backfillable over
   whatever artifact history exists.

5. `0005-below-floor-mu` — serve μ for constraints under the serving floor as a
   query filter, not a payload change. Fixes the dashed amber rows: 62 elements bound on
   ≥24 of the last 30 days and 43 are outside the cast, including `BRUNI_69_1` (27 of 30,
   median Σμ $611, settled $2,724). Turns "no opinion" into "predicted nothing on an
   element that binds almost daily."

6. `0006-grade-panel` — replace the three grade cells, which currently count join
   membership, with real Σμ scoring forecast-against-settled. Watch the two known traps:
   the universe trap (scoring only what was forecast) and the base-rate trap. Do not
   blend constraint and node halves into one number — signed errors net to "balanced"
   while both halves are badly low (`0003`). Depends on `0002`, `0004` and `0005`.

7. `0007-sp-history` — persist or roll up daily hub & zone congestion for the
   board's 30-day track, currently `mock`. Depends on `0002`'s window layer.

**Phase 3 — refinement.**

8. `0008-essp-ingest` — **last of the three foundations.** ESSP is a refinement over two
   dedupe methods that already work: coordinate clustering
   (`compute/analysis/families.py:334`) and exact-24h price identity, both listed `real`
   in the data-status table. What it adds is a *pre-DAM* grouping — ERCOT publishes
   NP4-158-SG before 06:00 as a DAM study — which price identity cannot give you on the
   morning read, plus the cases coordinates cannot see (`BAFFIN_ALL` / `PENA_ALL` /
   `STELLA_RN` / `TGW_T1_T2` are one location at four coordinates). It also needs new
   ingest and migrations (the feed table is now migration 40 and its daily score fields
   are migration 41), the highest cost of the three
   for the narrowest unblock. Until it lands, every count that dedupes nodes is
   conservative and should say so — `0002` stamps `"dedupe":"coordinate"` for this reason.

**Phase 4 — the page.**

9. `0009-brief-page-v6` — build `BriefPage.tsx` as the v6 layout and route `/`
   to it; un-mount the scrubber from the Brief only. **`/map` and `/matrix` keep the
   scrubber exactly as today** — this is one page's composition changing, not a
   teardown, and `0128`'s time-coordinate refactor is not touched.

10. `0010-date-window-picker` — a single-date `📅 Load Date` control on the brief page,
    reusing `DateRangePicker`'s dropdown and curated-events wiring. **Ships with
    `0009`**: un-mounting the scrubber removes the page's only way to change day.
    `?date` is retired; the cursor is the only day source.

11. `0011-hero-map-deeplink` — an inline map in the hero linking into `/map` at the
    day's window, autoplaying the forecast. Standalone because it adds three URL
    params (`mapView`, `data`, `autoplay`) that have no reader today. This is the
    entire product for a reader who does not know what a shadow price is.

**Phase 5 — teardown.**

12. `0012-remove-legacy-analysis` — delete the precomputed-brief stack once nothing
    reads it: `build_brief`, `after_action`, the brief jobs, `analysis_brief`, and the
    `/analysis/brief` endpoints. Keep `load_sp_metadata` and the `brief.py` primitives
    `0003` routes; audit `families.py` per function rather than deleting the file.

## Branching

One branch per sub-plan, named in each file's `Branch:` line
(`feat/0129-0002-hero-generator`, …). Each carries a `Depends on:` line directly under
it — read that first; it is the only thing standing between a sequential sprint and a
merge conflict.

Two notes on that:

* **`0009` and `0010` are two branches but one release.** Merge `0010` before `/`
  goes live, or the brief ships with no way to change day. Branch `0010` off `0009`
  rather than off `master`.
* **`0003`, `0005` and `0008` have no dependencies** and can run in parallel with the
  `0002` line whenever there is capacity. Everything else is strictly sequential on
  what its `Depends on:` names.

## Out of scope

* `day.regimes`, `day.hub_board`, `day.grade` — prototype-only constructs that exist
  nowhere in `compute/` or `api/`. The hero removes `regimes` from the critical path;
  the board and grade are rebuilt from queries in 6 and 7, not as blob additions.
* Transmission outages — `blocked`, and not by us. Every public ERCOT outage product is
  resource-side; transmission detail needs a Market Participant certificate for the MIS
  Secure Area. Nothing in this rebuild should assume it arrives.
* Widening `analysis_brief`, or adding hero/editorial fields to `build_brief`.
* Re-doing `0128`'s time-coordinate refactor. The scrubber *UI* leaves the brief page;
  `useTimeCursor`, `snapToFrames` and the `?t/?span/?run/?ws/?we` contract stay exactly
  as they are, and Map and Matrix keep their scrubber untouched.
* The Scoreboard page — a sibling route outside the shared session, unaffected by any
  of this.
