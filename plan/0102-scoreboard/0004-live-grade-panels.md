# 0004 - live-grade-panels

Type: feat
Branch: feat/0004-live-grade-panels

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Render the per-delivery-day grade panel on the scoreboard page — "how did yesterday's forecast do" — fed by `GET /scoreboard/daily`.
* Render the miss-attribution panel for a selected day, decomposing the miss into unforecastable-outage / driver-forecast bust / model error, fed by `GET /scoreboard/miss?date`.
* Wire both into the existing 0002 scoreboard page, keeping baselines + oracle in frame per the integrity rule.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* This is the web half of the live daily-grading track — it visualizes the grades + decomposition that 0003 computes and serves (`spec-phase3-scoreboard.md` §5 per-day panel, §8 step 4).
* Depends on 0003 (`/scoreboard/daily`, `/scoreboard/miss`) and on the 0002 page existing to host the panels; therefore lands after Phase 2, once `forecast_day` is producing panels and a day of grades exists.
* Miss-attribution is what makes a bad day diagnostic rather than merely honest — surface the three buckets, not a lone error number (spec §4).
* Integrity: never render a model figure without its persistence delta + oracle ceiling (spec §6).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `web/src/api.ts` (client bindings for `/scoreboard/daily` + `/scoreboard/miss`), `web/src/components/` (new per-day grade + miss-attribution panels), the 0002 scoreboard page/route (mount the panels).
* Per-day grade panel: show the most-recent delivery day's grade with the day selectable; each metric carries its persistence delta + oracle ceiling (spec §5, §6).
* Miss-attribution panel: for the selected day, render the decomposition (unforecastable-outage / driver-forecast bust / model error) as a labelled breakdown so the miss is diagnostic (spec §4).
* Load the `dataviz` skill before any chart/breakdown visual; match the 0002 page's tile/series styling so the live half reads as one system with the backtest half.
* Do NOT: recompute grades or decomposition client-side — render what 0003 serves; do NOT touch the backtest series/endpoints (0001/0002) or the grading job (0003).

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] The scoreboard page shows a per-delivery-day grade panel fed by `GET /scoreboard/daily`, with the day selectable. — `LiveGradePanel` in `web/src/pages/ScoreboardPage.tsx`, day `<select>` over the run's graded delivery days.
* [x] Each per-day metric renders with its persistence delta and oracle ceiling — no lone model figure (spec §6). — four tiles (top-decile / rank ρ / sign / pooled R²), each carrying the model figure, `▲/▼ vs persist`, and the oracle ceiling.
* [ ] ~~The miss-attribution panel renders the three-bucket decomposition (unforecastable-outage / driver-forecast bust / model error) for a selected day from `GET /scoreboard/miss?date`.~~ **DEFERRED** — miss-attribution (`/scoreboard/miss` + the `scoreboard_miss` decomposition + its prediction-time snapshot) was deferred out of 0003 and never built (`compute/jobs/grade_day.py`, `db/migrations/35_scoreboard_daily.sql`, `api/models.py` all note it). It cannot be built web-only; when its backend lands it returns as a follow-up panel.
* [x] Both panels mount on the 0002 scoreboard page and are absent/graceful before any live grade exists. — the daily panel mounts on the 0002 page and is absent when `/scoreboard/daily` 503s (`fetchScoreboardDaily` → null); the miss panel is deferred per above.
* [x] No grade or decomposition is recomputed client-side — the panels render server-served values. — `LiveGradePanel` renders `DailyPoint` values verbatim; deltas are display-only differences of served figures.
