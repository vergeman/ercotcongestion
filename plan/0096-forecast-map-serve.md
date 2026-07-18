# 0096 - forecast-map-serve

Type: feat
Branch: feat/0096-forecast-map-serve

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Serve per-hour, per-SP forecast congestion (P10/P50/P90) from `forecast_nodal` via a new **time-indexed range** endpoint `GET /forecast_range`, mirroring `/ercot_spp_range` so the prediction pane aligns to the same scrubber as the realized panes.
* Key the endpoint on the two axes the schema already has: `ts` (target time — the scrubber) and `run_id` (the *model version*, not a day — one run accumulates many `delivery_date`s). `run_id` is an optional selector (default: the promoted `forecast_current[ercot]` run); omitting `start`/`end` serves that run's latest operating day — the default landing view, cursor snapped to now.
* Repoint the left "prediction" `GridMap` from the realized placeholder to the forecast source (P50 for the fill) so the two panes stop rendering identical data; the forecast defines the landing window and the realized ranges are fetched to match.
* Resolve predicted LMP on the prediction side as predicted congestion (P50) + the per-hour system-λ reference — the same λ the market side subtracts, so the LMP comparison collapses to the congestion one (needed by 0098).

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* Compute already writes `forecast_nodal` (P10/P50/P90 congestion) + the SF+μ artifact — `compute/jobs/daily_forecast.py::persist_forecast`, migrations `db/migrations/30_forecast_nodal.sql`, `31_forecast_sf_artifact.sql`. The "one true compute blocker" (nodal-panel emission) is already resolved; this is a serving/wiring job.
* No forecast API route exists today (`api/map.py` serves only SF structure: meta/constraints/exposures/reach/overview). The left pane is an explicit placeholder rendering realized values — `web/src/App.tsx:54` and `:486` ("Both render the same quantity").
* Linchpin of the sprint: buckets 0097/0098/0099 all decorate a comparison that is vacuous until the left side is a real forecast.
* **Design note (supersedes the original `/map/forecast` sketch):** the forecast is served as a *time-indexed range* (`api/forecast.py`, the `_range` family), not a snapshot in the not-time-indexed `/map/*` router. `run_id` = model version (`daily_forecast.py:71`: "names the MODEL VERSION, not the day"), so one run already spans a whole history of `delivery_date`s — history and backfill need no per-day pointer table; a specific `run_id` just A/Bs a different model over the same target-time axis. Backfilled days are only honest if generated as-of each day (walk-forward, no future leak) — enforced in the compute job, not the API.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `api/forecast.py` (new router), `api/models.py` (response schema), `api/main.py` (mount), `web/src/api/{types,client,prefetch}.ts` (types + fetcher + cache), `web/src/App.tsx` (state + wiring); `web/src/components/map/GridMap.tsx` only if the prediction pane needs a distinct data prop.
* Entry point / primary change: new `GET /forecast_range?run_id=<opt>&start=<opt>&end=<opt>` in `api/forecast.py`, modeled on `api/ercot_spp.py`. Resolves `run_id` (explicit param, else `forecast_current[ercot]`), resolves the window (explicit `start`+`end`, else the run's latest operating day via `MIN(ts)/MAX(ts)` of its `MAX(delivery_date)` — the stored `ts` span, so the CT operating day and DST come from the data, not client UTC-midnight math), and returns a range payload: `{start, end, run_id, count, entries:[{interval_ts, system_lambda, sps:[{sp_id, p10, p50, p90}]}]}`. Expanded vs `ErcotSppRangeResponse` with the P10/P50/P90 triple + per-hour system-λ. 503 soft-fail (no run published / no rows in window), matching the realized ranges.
* Schemas in `api/models.py`: `ForecastSpState` / `ForecastRangeEntry` / `ForecastRangeResponse`.
* Frontend: `fetchForecastRange(start?, end?)` client (no-arg = default landing call); `ForecastRange*` types; a `forecastCache` in `prefetch.ts` unioned into the scrubber timeline. `prefetchWindow(start?, end?)` is forecast-led when no window is given — fetch the forecast first, then the realized ranges for the span its response reports.
* Wire the left `GridMap` (`side="prediction"`) to per-hour forecast rows (P50 → fill) read off the same scrubber index as the realized rows; keep the right pane on realized ERCOT. Coloring: prefer the realized palette scale when both exist (comparable), fall back to a forecast-derived scale on a forecast-only day.
* Predicted LMP display = predicted congestion (P50) + the hour's `dam_system_lambda` (NP4-523-CD) carried on each entry — the same reference the market side already uses (`api/ercot_state.py` computes congestion as `SPP − system_λ` via `load_congestion_panel(ref_method="system_lambda")`, and `compute/sf/persist.py` pins `REQUIRED_REF_METHOD = "system_lambda"`). Because both sides subtract the same λ, LMP-basis collapses to congestion-basis exactly (needed by 0098).
* Do NOT touch: the right/actual pane data path, the SF overlay endpoints, or scoreboard.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `GET /forecast_range` returns per-hour, per-SP P10/P50/P90 congestion; a spot (SP, hour) equals its `forecast_nodal` row.
* [ ] A bare `GET /forecast_range` (no params) returns the promoted run's latest operating day (24h); `?run_id=` selects a specific model version; `?start=&end=` scrubs an explicit window. Each 503s (not empties) when nothing matches.
* [ ] On landing the app loads the default forecast day with the cursor at now; the realized ranges are fetched for the window the forecast reports.
* [ ] Left ("prediction") pane renders forecast values that are visibly distinct from the right ("actual") pane — the two are no longer identical.
* [ ] Palette congestion and LMP both resolve on the prediction side (LMP = P50 + the hour's system-λ), including on a forecast-only (future) day with no realized rows.
* [ ] Response carries `run_id` and the resolved `start`/`end` so the client can label which model version and day it is serving.
