# 0158 - map supporting-data fallback and brief link

Type: fix
Branch: fix/0158-map-supporting-data-fallback-and-brief-link

## Goal

* Show the available forecast for load, wind, and solar in ERCOT/Compare views when ERCOT actual data for that group has not published, marked in its label as `(Forecast)`.
* Keep actual ERCOT supporting-market values unmarked whenever they are present.
* Make the Brief hero open t+2 forecast days in the Forecast map view and settled days in the ERCOT market view.

## Context

* `/conditions_range` already supplies `forecast_mw` and `actual_mw` together for every load/wind/solar row; the sidebar currently selects only actual values in Market/Compare, producing `—` when the supporting reports lag DAM settlement.
* The Brief hero’s map CTA always serializes `view=market&data=lmp`; therefore a t+2 hero explicitly asks for an ERCOT market map even though its provenance is forecast.
* A t+1 day can have settled DAM prices while one or more supporting rows remain unpublished. The fallback must be decided per displayed row, not from the day-wide Brief basis.

## Approach

### Commit 1 — mark per-row forecast substitutions in Map Conditions

* Work in: `web/src/components/panels/SidePanel.tsx`.
* Replace the numeric `regionMw` selector with a small display resolver for load/wind/solar rows. Forecast and Error retain the forecast value without a suffix; ERCOT/Compare prefer `actual_mw`, otherwise use a non-null `forecast_mw` and return `isForecast: true`.
* Render fallback values with their normal `#,### MW` format. When a group is using forecast support, change its caret label to `Load by Region (Forecast)`, `Wind Generation (Forecast)`, or `Solar Generation (Forecast)`; keep `—` when neither side has a value.
* Apply the fallback independently to Load by Region, Wind Generation, and Solar Generation. Derive the label from the group’s system value so the label is stable while its expanded regional rows render their own matching actual-or-forecast values. Keep Outages by Fuel on its current actual-or-empty behavior; it is a distinct daily-vintage quantity.
* Preserve all payload contracts, range fetching, map colors, and the Forecast/Error selection behavior; this is a presentation fallback over data already in the cache.

### Commit 2 — build the Brief hero CTA from its proven map basis

* Work in: `web/src/pages/BriefPage.tsx` and, if extraction is warranted for a testable pure helper, `web/src/lib/mapLinks.ts`.
* Choose the CTA view from `hero.provenance.basis`: settled heroes build the existing `market` + LMP autoplay link; forecast heroes (including t+2) build `forecast` + LMP autoplay instead.
* Change the CTA copy with the same condition: settled reads “Watch prices move across the day →”; forecast reads exactly “Watch the latest price forecast →”. Keep the CTA’s full-day `t/ws/we` coordinate and one-shot `autoPlay` behavior unchanged.
* Do not use the availability of load/wind/solar actuals to choose the hero’s main map view. DAM settlement controls the price basis; supporting-data fallback remains local to the Conditions sidebar.

### Commit 3 — verify the two independent late-publication cases

* Work in: focused frontend checks and existing API test coverage only as needed; no API/schema migration is expected.
* Add a focused test for the extracted Conditions resolver if the project’s test setup can run it without introducing a new test framework. Otherwise cover the cases through TypeScript/build verification and a documented manual Map smoke test.
* Exercise a settled cursor with null actual + non-null forecast for each of load, wind, and solar: ERCOT and Compare show the normal forecast number and mark the corresponding group label `(Forecast)`; Forecast/Error remain forecast values without a marker; a populated actual remains unmarked.
* Exercise Brief heroes for a settled t+1 and forecast t+2 artifact. Assert their generated links use, respectively, `view=market` and `view=forecast`, both retain `data=lmp`, the delivery-day bounds, and `autoPlay=true`; verify the corresponding CTA wording.
* Run `npm run build` from `web/` (or the repository’s equivalent TypeScript check) and the focused API/frontend tests available in the checkout.

## Acceptance

* [x] In ERCOT and Compare, missing actual load/wind/solar rows show their matching forecast value instead of `—`, and the applicable group label is marked `(Forecast)`.
* [x] Rows with actual ERCOT values remain actual and have no forecast suffix; rows with neither value remain `—`.
* [x] A t+2 Brief hero opens Forecast × Price (LMP), autoplays the full day, and says “Watch the latest price forecast →”.
* [x] A settled Brief hero continues to open ERCOT × Price (LMP), autoplays the full day, and says “Watch prices move across the day →”.
* [x] Existing Conditions API contracts and Outages display behavior are unchanged; the web build/type check passes.
