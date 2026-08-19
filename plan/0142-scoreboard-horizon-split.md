# 0142 - scoreboard-horizon-split

Type: fix
Branch: fix/0142-scoreboard-horizon-split

## Goal

* Serve one horizon per live board: filter `/scoreboard/daily` on horizon and
  return it on every point.
* Let the Scoreboard page switch tracks (final t+1 / preview t+2) and always label
  which one is displayed.
* Label every block on the Scoreboard page with what it measures and over what span.
* Document the three grade surfaces, their jobs, and their cadences in `docs/scoring.md`.

## Context

* `scoreboard_daily` is keyed `(run_id, delivery_date, source, horizon)`, but
  `/scoreboard/daily` queried `WHERE run_id = %s` with no horizon predicate — a
  pre-horizon endpoint left unchanged when the preview cron started grading (2026-07-31).
* Result: two rows per (delivery_date, source); `ScoreboardPage.tsx` keys by source
  alone (`m.set(p.source, p)`), so the board showed whichever row arrived last. A
  **preview** grade could render as the served forecast — on 2026-08-16, mae 1.92 vs 2.33.
* The page's four blocks (live tiles, headline tiles, weekly chart, split table) are
  four different measurements over four different spans, previously distinguishable
  only by shape.
* Out of scope: `scoreboard_weekly` has no horizon concept (offline backtest); the
  0133 backfill is unaffected.

## Approach

* Work in: `api/scoreboard.py`, `api/models.py`, `web/src/pages/ScoreboardPage.tsx`,
  `web/src/api/{client,types}.ts`, `docs/scoring.md`; tests beside each.
* Entry point: `get_scoreboard_daily` + new `_resolve_daily_horizon`.
* Add `_resolve_daily_horizon(cur, run_id, horizon)`: `SELECT DISTINCT horizon` for the
  run; explicit request wins; else h1 when graded, else the only graded track. An
  ungraded explicit horizon returns no rows and falls through to the existing 503 —
  no second failure mode.
* Filter the per-day SELECT on horizon, add `horizon` to its columns and to
  `DailyPoint`; return `horizon` + `horizons` on `ScoreboardDaily`.
* Thread `horizon` through `/scoreboard/summary` (live section only) and
  `fetchScoreboardSummary(regime, horizon)`; hold it as page state alongside `regime`.
* Render a track selector when `horizons.length > 1`, else a plain label — the track
  is always named.
* Add `.sb-section-h` headings above the headline tiles and weekly chart; reword the
  split table's; move the live heading onto its own line so all four share a left edge.
* Do NOT touch: `grade_day`, `scoreboard_daily`'s schema, or any backtest path.

## Acceptance

* [x] `/scoreboard/daily` returns exactly one horizon's rows; `horizon` present on
      every point and on the envelope, `horizons` lists the graded tracks.
* [x] Omitted `horizon` serves the final track; a run that graded only h2 serves h2;
      an ungraded requested horizon 503s naming it.
* [x] Page shows the track name always, a selector when both exist, and refetches
      the bundle on switch.
* [x] Four blocks carry headings sharing one left edge.
* [x] `api/tests/test_scoreboard_daily.py` covers default / explicit / fallback /
      503-by-horizon (10 passed); `test_scoreboard_summary.py` asserts the new
      pass-through arity; `tsc -b` clean. Three `test_analysis.py` failures pre-date
      this branch (verified on a clean master).
* [x] `docs/scoring.md` maps each panel to its dataset, job, cadence, and backfill path.
