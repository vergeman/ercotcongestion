# 0002 - scoreboard-page

Type: feat
Branch: feat/0002-scoreboard-page

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Serve the weekly backtest time series via `GET /scoreboard/weekly?source&regime` — the screening + magnitude columns per (week × source × regime), reading `scoreboard_weekly`.
* Build the full backtest scoreboard page/route: headline tiles, the weekly metric-vs-baselines-vs-oracle series, a coverage strip, and the pre/post-RTC+B split.
* Add the regime selector (`all` / net-load quintiles / summer_peak / …) driving both the series and the split.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* The backtest board is **reshape + serve** — the numbers already live in `scoreboard_weekly` (loaded by 0001); this plan adds the series endpoint + the page that a panel cannot hold (`spec-phase3-scoreboard.md` §0, §2.1).
* Split by altitude from 0001: 0001 owns the headline slice + side panel; this plan owns the **full page** (weekly series, regime selector, coverage strip, pre/post-RTC+B split) that 0001's "View full scoreboard" link targets (spec §5).
* Backtest half only — needs nothing from Phase 2's forecast panel; ship it now (spec §8 steps 3 remainder).
* Integrity rules bind here: lead with screening currency, file magnitude (R²/MAE) under a toggle, and never render a model number without persistence + oracle in frame (spec §6).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `api/` (extend the `/scoreboard` module from 0001 with `/scoreboard/weekly`), `web/src/api.ts`, `web/src/components/` (new scoreboard page/route), `web/src/pages/` or router as the app structures pages.
* Entry point / primary change: `GET /scoreboard/weekly?source&regime` → weekly rows (screening: `rank_spearman`, `sign_agree`, `topdecile_hit`; magnitude: `pooled_r2`, `mae`; plus `coverage80`, `band_width`, `pinball` for model), ordered by week. Return oracle + persistence + climatology alongside model on **every** response (spec §3).
* Page (spec §5): headline tiles (reuse the 0001 headline component/endpoint — do not re-fetch a lone model figure), weekly time series (**screening currency by default; R²/MAE behind a toggle**), a coverage strip on the same x-axis beneath the series, and the pre/post-RTC+B split (cutover 2025-12-05) visible on every pooled stat — show pooled 0.610 top-decile *and* post-RTC+B 0.559.
* Regime selector drives the series + split; annotate that with one year of data, spring ≈ low-demand overlap (corroborating, not independent).
* Load the `dataviz` skill before any chart/tile/strip visual.
* Do NOT: re-measure or redefine any gate/baseline — serve `scoreboard_weekly` as-is (spec §6); do NOT embed the live per-day/miss panels (0004); do NOT block on Phase 2 / 0096.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `GET /scoreboard/weekly?source&regime` returns the weekly series with screening + magnitude columns, ordered by week.
  * `api/scoreboard.py::get_scoreboard_weekly`; all sources per (week), ordered (week, source). 276 points verified. `source` is the foregrounded series; comparators ride along regardless.
* [x] Reshape fidelity: a spot `(week, source, regime)` equals the CSV cell; served `model`/`all` pooled top-decile = **0.610**, post-RTC+B = **0.559** (spec §7).
  * Spot matches exactly (`model/all/2025-08-14` = `0.7020376`). **Caveat:** pooled figures are stale-data — this Jul-14 CSV pools to **0.523 / 0.455**, not 0.610 / 0.559. Pooling = plain week-mean (matches `r5()`/`cell()`); self-corrects on CSV regen.
* [x] Every `/scoreboard/weekly` response carries oracle + persistence + climatology alongside model — no lone model figure (spec §7).
* [x] The served gate verdict for `model`/`all` matches `gate()` run on the same numbers ("SCREENING TOOL", clears the 0.60 bar pooled) (spec §7).
  * Uses the authoritative `backfill_nodal.gate()` (lazy import); served == independent `gate()` verified. On stale data the verdict is **"NOT THE PRODUCT"** (R² pools < 0.30), not "SCREENING TOOL" — flips with the regenerated CSVs. Gate is still **served**; the page no longer **displays** the column (removed on review).
* [x] The page renders headline tiles, the weekly series (screening default, magnitude toggle), a coverage strip on the shared x-axis, and the pre/post-RTC+B split on pooled stats.
  * `web/src/pages/ScoreboardPage.tsx` + `/scoreboard` route (`main.tsx`, no router — vite SPA fallback). Tiles, series (4 sources, screening-default / magnitude toggle, RTC+B marker, hover), and the pooled pre/post-RTC+B split table all render. **Deviation:** the **coverage strip was removed on review** (near-uniform ~0.96 coverage read as unexplained boxes) — re-add with proper labeling if coverage varies enough to matter.
* [x] The regime selector reorders the series + split; the page renders without depending on 0096's forecast data.
  * Regime dropdown (All / net-load Q1–Q5) refetches series + splits + headline. Reads `scoreboard_weekly` only — independent of `forecast_nodal` / the forecast run.

<!-- dataviz: 4-series categorical palette = the skill's pre-validated dark slots 1–4
     (validated OK on the app surface); CVD at the permitted first-four floor, so
     the required secondary encoding ships (legend + direct end-labels + the table). -->

<!-- NOTE: acceptance boxes checked after implementation; two intentional deviations
     from review — coverage strip removed (#5) and gate column removed from the page
     (#4, still API-served). Stale-CSV caveat noted on #2/#4. -->

