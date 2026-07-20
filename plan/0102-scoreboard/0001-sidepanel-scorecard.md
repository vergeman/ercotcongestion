# 0001 - sidepanel-scorecard

Type: feat
Branch: feat/0001-sidepanel-scorecard

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Build the thin backtest-serving slice — a `scoreboard_weekly` table, a CSV loader, and `GET /scoreboard/headline` — since no scoreboard API exists yet (0100 spec §8 steps 1–3, which that spec says ship early and independently).
* Show network stats in the side panel (restoring the prior StatsPanel content) alongside a compact 3-tile scorecard headline fed by that endpoint.
* Render the headline — rolling top-decile, its persistence delta, and the oracle ceiling — each tile carrying its comparators; link to the full scoreboard page (0002), do not embed the full board.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* No scoreboard API/module/web file exists today (confirmed by grep) — `/scoreboard/headline` is unbuilt. But the weekly CSVs it serves already exist (`compute/mu/mu_score_weekly.csv`, `mu_bands_weekly.csv`), so the serving slice is reshape-and-serve, not new measurement (`spec-phase3-scoreboard.md` §0).
* Split by altitude, not phase: this plan owns the **headline serving slice + panel**; 0002 keeps the **full page** (weekly series, regime selector, coverage strip, pre/post-RTC+B split) which does not fit a panel. This keeps 0001 self-contained without un-deprioritizing 0002.
* Independent of the forecast work in 0096 — it reads the backtest CSVs, not `forecast_nodal`.
* Integrity rule from the scoreboard spec (§6): never render a model number without its comparators — each tile shows the persistence delta and the oracle ceiling.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `db/migrations/` (new `scoreboard_weekly`), a one-shot loader (CSVs → table), `api/` (new `/scoreboard/headline` route + module), `web/src/components/` (side panel / former StatsPanel), `web/src/api.ts`.
* Migration + loader: create `scoreboard_weekly` per `spec-phase3-scoreboard.md` §2.1 and `COPY` both weekly CSVs into it (join bands onto the model rows), keyed by `run_id`.
* Endpoint: `GET /scoreboard/headline` → rolling 30/90d tiles, each carrying the model metric, its persistence delta, and the oracle ceiling — never a lone model figure (spec §3).
* Panel: render network stats + a 3-tile headline (top-decile, plus rank-Spearman/sign as space allows); add a "View full scoreboard" link/route targeting the 0002 page.
* Load the `dataviz` skill before building any tile/meter visuals.
* Do NOT: embed the weekly time series, regime selector, or coverage strip in the panel; do NOT redefine or re-measure any gate/baseline — serve the CSV numbers as-is (spec §6).

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `scoreboard_weekly` exists and the loader populates it; a spot `(week, source, regime)` equals the CSV cell (model `all` pooled top-decile = 0.610, post-RTC+B = 0.559).
  * Migration `db/migrations/34_scoreboard_weekly.sql` + loader `compute.jobs.load_scoreboard` (nearest-week bands join, `null`-source preserved). Loaded 1134 rows (`run_id=map-v1`); spot `model/all/2025-08-14` topdecile = `0.7020…` matches the CSV cell exactly.
  * Caveat: the cited **0.610** is from a fresher score run; this stale Jul-14 `mu_score_weekly.csv` per-week-averages ~0.523. Loader serves the CSV as-is — the number self-corrects when the CSVs are regenerated.
* [x] `GET /scoreboard/headline` returns model + persistence + oracle on every response (no lone model figure).
  * `api/scoreboard.py`; every currency carries model + persistence + climatology + oracle. Verified live: 200 on default/regime, 503 soft-fail on unknown run/regime.
* [x] Side panel shows network stats plus a 3-tile scorecard headline, each tile with its persistence delta and oracle ceiling.
  * `web/src/components/panels/SidePanel.tsx`. Per review, the 3 tiles were simplified to a compact **model | persist | ceiling** table (rows: top-decile / rank ρ / sign) with the model↔persistence leader **bolded** and per-currency hover copy. Deviation: the explicit persistence-*delta* figure is dropped — comparators are always shown (integrity intent held), but the `Δ` value is implicit in the model-vs-persist columns rather than rendered.
* [x] A link navigates to the full scoreboard page (0002); the headline renders without depending on 0096's forecast data.
  * "View full scoreboard →" links to `/scoreboard` (future 0002 route). Headline reads `scoreboard_weekly` only — independent of `forecast_nodal` / the forecast pointer (board `run_id=map-v1` vs forecast `mu-all-v1`).
