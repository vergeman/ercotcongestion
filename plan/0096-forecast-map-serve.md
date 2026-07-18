# 0096 - forecast-map-serve

Type: feat
Branch: feat/0096-forecast-map-serve

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Serve per-SP forecast congestion (P10/P50/P90) for the served delivery day from `forecast_nodal` via a new map API route.
* Repoint the left "prediction" `GridMap` from the realized placeholder to the forecast source so the two panes stop rendering identical data.
* Resolve predicted LMP on the prediction side as predicted congestion + a fixed system-λ reference (predicted congestion is the native μ output).

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* Compute already writes `forecast_nodal` (P10/P50/P90 congestion) + the SF+μ artifact — `compute/jobs/daily_forecast.py::persist_forecast`, migrations `db/migrations/30_forecast_nodal.sql`, `31_forecast_sf_artifact.sql`. The "one true compute blocker" (nodal-panel emission) is already resolved; this is a serving/wiring job.
* No forecast API route exists today (`api/map.py` serves only SF structure: meta/constraints/exposures/reach/overview). The left pane is an explicit placeholder rendering realized values — `web/src/App.tsx:54` and `:486` ("Both render the same quantity").
* Linchpin of the sprint: buckets 0097/0098/0099 all decorate a comparison that is vacuous until the left side is a real forecast.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `api/map.py`, `api/models.py` (response schema), `web/src/api.ts` (fetcher + types), `web/src/App.tsx` (state + wiring); `web/src/components/map/GridMap.tsx` only if the prediction pane needs a distinct data prop.
* Entry point / primary change: new `GET /map/forecast` in `api/map.py` reading `forecast_nodal` for the served `run_id` / delivery day → per-SP `{sp_id, p10, p50, p90}` congestion.
* Add a `fetchMapForecast(...)` client + response type; add prediction-side state parallel to the existing congestion/SPP caches.
* Wire the left `GridMap` (`side="prediction"`) to the forecast rows (P50 for the fill) instead of the realized merge; keep the right pane on realized ERCOT.
* Predicted LMP display = predicted congestion + `dam_system_lambda` (NP4-523-CD) for the delivery day — the same reference the market side already uses (`api/ercot_state.py` computes congestion as `SPP − system_λ` via `load_congestion_panel(ref_method="system_lambda")`, and `compute/sf/persist.py` pins `REQUIRED_REF_METHOD = "system_lambda"`). Reuse it on both palettes; because both sides subtract the same λ, LMP-basis collapses to congestion-basis exactly (needed by 0098).
* Do NOT touch: the right/actual pane data path, the SF overlay endpoints, or scoreboard.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `GET /map/forecast` returns per-SP P10/P50/P90 congestion for the served delivery day; a spot SP equals its `forecast_nodal` row.
* [ ] Left ("prediction") pane renders forecast values that are visibly distinct from the right ("actual") pane — the two are no longer identical.
* [ ] Palette congestion and LMP both resolve on the prediction side (LMP = predicted congestion + system-λ reference).
* [ ] Response carries `run_id` and delivery date so the client can label which refit/day it is serving.
