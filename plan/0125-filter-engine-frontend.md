# 0125 - filter-engine-frontend

Type: feat
Branch: feat/0125-filter-engine-frontend

## Goal

* Ship the **Analysis** page: a single-delivery-day Insight Brief that renders the 0124 brief (F1–F6) for one day, defaulting to the latest, with a "previous day" button to step back through history.
* Lead with the F5b separation story + F6 after-action ("what mattered"), F1–F5a behind progressive disclosure; an hour selector walks the day's 24 hours.
* Enable the disabled `Analysis` nav item and route the page at `/analysis?date=YYYY-MM-DD`.

## Context

* 0124 built `GET /analysis/brief?delivery_date=…` → one day's full brief (`provenance`, `hours[iso]` with F1–F6, `day` roll-up). ~190KB/day; `available:false` (not 404) when absent. **Left frozen** — this plan adds a sibling endpoint instead of changing it.
* That endpoint **requires** `delivery_date` and knows nothing about which days exist — the page can't resolve "latest" or know where "previous" points (history has gaps). Commit 1's new `/analysis/brief/latest` closes that.
* Frontend conventions to match: react-router pages (`main.tsx`), `HeaderNav` topbar + two-pane body, hand-rolled SVG, `client.ts` soft-fail (503/absent → null) fetchers, CSS vars + `tabular-nums`, the `Term`/`Tooltip` glossary, and the dataviz palette — all in `pages/ScoreboardPage.tsx`. The `LiveGradePanel` day-selector is the pattern for the hour selector.
* Horizon: page shows the **served** horizon per day (endpoint already coalesces final→preview) with a badge; a strict-t+2 or a toggle is a later flip, not v1.

## Approach

### Commit 1 — backend: new `GET /analysis/brief/latest`

* Work in: `api/analysis.py` (new route; leave `GET /analysis/brief` untouched).
* Resolve the run (same `forecast_current` logic as the sibling), pick the latest `analysis_brief` day (`max(delivery_date)`), and return the **same envelope** the per-day endpoint returns for that day (`available`, `run_id`, `delivery_date`, `horizon`, `computed_at`, `brief`).
* Also return `available_dates`: the sorted list of delivery_dates that have a brief for the run (dates only — cheap). The page derives prev/next as array neighbors, so gaps are skipped and stepping chains indefinitely, all while fetching each day through the frozen `GET /analysis/brief?delivery_date=`.
* `available:false` when no brief exists at all (empty `available_dates`), matching the soft-fail contract.
* Do NOT modify `GET /analysis/brief`; do NOT add a list/pagination endpoint — single-day view only.

### Commit 2 — frontend scaffold: route, nav, client, day-nav header

* Work in: `web/src/main.tsx`, `web/src/components/layout/HeaderNav.tsx`, `web/src/api/{client,types}.ts`, new `web/src/pages/AnalysisPage.tsx`.
* Add two fetchers to `client.ts` (both soft-fail → null): `fetchAnalysisBriefLatest()` (→ `/analysis/brief/latest`) and `fetchAnalysisBrief(deliveryDate)` (→ the frozen per-day endpoint). Add the `AnalysisBrief` envelope + `available_dates` response types in `types.ts` mirroring the 0124 JSON shape.
* Route `/analysis` → `AnalysisPage` in `main.tsx`; in `HeaderNav`, give `analysis` an `href: "/analysis"` and drop it from the disabled branch.
* Page shell (reuse `ScoreboardPage` structure): `HeaderNav active="analysis"` topbar carrying provenance (run_id, delivery_date, horizon badge, `computed_at`, `dam_match_coverage`); a **day nav** driven by `available_dates` — "← Previous day" / forward arrow step to the neighbor date (disabled at the ends), "Latest" resets. On load call `/latest`; day steps fetch the neighbor via `fetchAnalysisBrief`. `date` lives in the URL query (`?date=`), default latest.
* Loading / `available:false` / null (soft-fail) empty states, same idiom as the scoreboard.
* Do NOT touch the Matrix or Map; no cross-page deep links in v1.

### Commit 3 — the "what matters" story (F5b + F5a) + hour selector

* Work in: `AnalysisPage.tsx`.
* Hour selector (LiveGradePanel pattern) over the 24 `hours` keys, defaulting to the day roll-up's `peak_hours.by_hour_score`; a "day summary" mode reads `day` (daily_ranks, peak hours, watchlist).
* Headline card from the hour's `best_pair`: sink↔source with congestion, forecast `spread`, `dominance_share`, and a **driver waterfall** (per-constraint `contribution`, summing to spread) — the SVG/DOM waterfall from last_mile.md's "Show drivers".
* One-line F5a market read from `hub_dipole` (min/max hub, spread, top driver).
* Do NOT re-rank or recompute anything client-side — render server values verbatim.

### Commit 4 — F6 after-action rendering

* Work in: `AnalysisPage.tsx`.
* When the hour's `after_action` is present: render the **spread decomposition** (`best_pair_decomposition` / `hub_dipole_decomposition`) as forecast → +Δμ → spatial residual → actual, and the **ranking scorecard** (`recall_at_k`, `exact_hits`, `biggest_severity_miss`, `biggest_false_alarm`, predicted rows with μ_forecast/μ_dam). Hub **triple** table with the P10–P90 `in_band` check.
* When `after_action` is null: a "pending DAM" state so the row reads as reconciled-later, not broken.
* Day-level `day.after_action.scorecard` summarized in the day-summary mode.

### Commit 5 — supporting families behind disclosure + glossary

* Work in: `AnalysisPage.tsx`.
* Expanders for F1 (`constraints` table — `hour_rank` vs `daily_rank` as distinct columns, μ, footprint), F2 (each constraint's `nodes.import`/`export` extrema), F3 (`stats` → archetype label derived at render: broad/systemic, strong separator, localized pocket), F4 (`hotspots` with the reinforcement-vs-cancellation `net_gross_ratio`, and `common_nodes`).
* Right-rail glossary (reuse `Term`/`Tooltip`): what a separation/driver/dipole/after-action means — the plain-language read `ScoreboardPage` established.
* Do NOT introduce a charting dependency — hand-rolled SVG/DOM only, matching the codebase.

## Acceptance

* [ ] `GET /analysis/brief/latest` returns the latest day's full brief envelope + `available_dates` (sorted); `GET /analysis/brief?delivery_date=` is unchanged.
* [ ] `/analysis` renders the latest brief on load; `Analysis` nav item is enabled and active.
* [ ] "Previous day" navigates to the prior date in `available_dates` and updates `?date=`; disabled at the earliest day. "Latest" returns to default.
* [ ] Hour selector walks all 24 hours; defaults to the day's peak hour; a day-summary mode shows daily ranks + watchlist.
* [ ] Best-pair story renders sink↔source, spread, dominance, and a driver waterfall that visibly sums to the spread (OLNEY↔LGW $159.19 on 2026-06-30 HE17).
* [ ] After-action renders the forecast→recon→actual decomposition + scorecard when present, and a "pending DAM" state when `after_action` is null.
* [ ] F1–F4 render behind expanders from server values only; no client-side re-ranking. Horizon badge + `dam_match_coverage` shown in provenance.
* [ ] Soft-fail: a day with no brief renders an empty state, never a thrown error.

### Deferred (note, per last_mile.md)

* Multi-day list / pagination; "Show in Matrix" / "Show on Map" cross-links; strict-t+2 filter or t+1/t+2 toggle; LLM commentary. Revisit once the single-day slice proves the workflow.
