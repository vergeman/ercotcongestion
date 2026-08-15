# 0133 - ct-delivery-day-blocks

Type: fix
Branch: fix/0133-ct-delivery-day-blocks

## Goal

* Cut the daily forecast block on the **CT delivery day** (05:00Z→05:00Z in CDT,
  DST-aware) instead of the UTC calendar day, so one artifact serves one Brief day.
* Restore the backtest's causal property that no DAM auction straddles a train/score
  boundary — eliminating the same-auction leak in the 5 CT-evening hours.
* Delete the two-artifact stitch in the API (and the `0132-brief-day-stitch-tail`
  fallback logic with it).
* Re-backfill all persisted forecast history on the new cut and re-materialize grades
  and scoreboards — with the preview (h2) track vintage-faithful to its live fire
  time, so pre/post-re-cut preview grades remain one continuous series.

## Context

* Today `daily_forecast` emits `[00:00Z, 24:00Z)` blocks (`_as_utc_day`,
  `daily_forecast.py:131`; `forward_hours`, `daily_forecast.py:320`). The `delivery_date`
  *label* is a CT calendar date and feature vintaging is per-interval CT
  (`features.py:83-109`), but the block itself is a UTC day — the CT evening of day D
  lives in artifact D+1.
* **Leak**: all 24 hours of CT day D clear in one DAM auction published ~13:30 CT on
  D−1. The D+1 fit trains on `interval_ts < 00:00Z of D+1`, which includes CT day D's
  daytime rows with published targets — then scores D's evening hours from the same
  auction. Backtest folds were CT-midnight-anchored (`mu_model.py:1024`, `score.py:382`)
  and never had this straddle; serving silently diverges from the validated
  configuration for 5 of every 24 displayed hours, and those hours leak into the
  self-grade.
* Storage convention is untouched by this plan: DB stores true UTC instants; day
  semantics (delivery day, DAM close, train cuts) are America/Chicago, converted at the
  boundary. The bug was one layer using UTC *calendar days* as its unit of work, not
  the storage timezone.
* Prod inventory to re-backfill: h1 2025-01-01→present (~592 days), h2
  2026-07-30→present (18 days); grades in `analysis_grade_daily`, rollups in
  `scoreboard_daily`/`scoreboard_weekly`.

## Approach

* Work in: `compute/jobs/daily_forecast.py`, `compute/mu/mu_model.py`,
  `compute/jobs/backfill_artifacts.py`, `api/analysis.py`; tests beside each.
* **Block anchor**: replace `_as_utc_day` with a CT-midnight anchor (label stays the CT
  calendar date — label and block finally agree). Generate the hour grid from
  `delivery_bounds(D)` (`compute/analysis/hero_window.py:21`), never `periods=24`:
  DST transition days are 23/25 hours.
* **`predict_day` gotchas** (`mu_model.py:656-661`): `D.normalize()` runs in the
  panel's tz (UTC) and would smash a CT midnight (05:00Z) back to 00:00Z — anchor on
  the passed instant, normalizing in CT if at all. The score block upper bound must be
  the *next CT midnight*, not `D + 24h`, for the same DST reason. Train stays
  `[D − 240d, D)`; with D at CT midnight the cut now excludes the entire day-D auction
  and gains the ~5 CT-evening D−1 hours the old cut wasted.
* **Freshness gate & logs**: re-derive the `daily_forecast` history-tail check
  (`daily_forecast.py:155`) and the CT log range (`daily_forecast.py:448`) from the CT
  bounds.
* **Verify, don't assume**: `propagate_window` / `compute/sf/project.py` consume the
  E_mu index by instant — confirm nothing re-anchors on UTC midnight; confirm the
  geo/wx map `score_from=D` phase-lock still holds with D at CT midnight (this makes
  serving match the backtest's CT phase, closing the eval/serving grid-phase split).
* **API**: collapse `_forecast_mu_profile`, `_forecast_node_profile`,
  `_daily_node_contributions` to a single `load_daily_artifact` + `delivery_bounds`
  filter. Remove the 0132 `tail_horizon`/`hours_covered`/truncation logic and response
  fields — one artifact now fully covers its day.
* **Rollout runbook** (live cutover — crons switch first, backfill converges behind):
  1. Ship `0132-brief-day-stitch-tail` first: with the D+1 artifact optional, a
     new-cut day renders fully through the *old* API path (concat + dedupe + CT-window
     filter already covers it), so the cron cutover needs no synchronized API deploy.
  2. Deploy the new compute image to `ercot-forecast` / `ercot-forecast-preview` and
     let them run — no suspension. Overwrites are keyed by
     `(run_id, delivery_date, horizon)` and `forecast_day` is deterministic, so a day
     emitted live and later re-backfilled converges to the same artifact (h2 included:
     the fire-time vintage cap uses the same historical instant either way).
  3. `backfill_artifacts --no-skip-existing`, **newest chunks first** (reverse date
     order): h2 2026-07-30→present, then h1 in reverse chunks back to 2025-01-01.
     Newest-first heals the one **seam day** quickly — the last old-cut day's CT
     evening exists in neither artifact until that day is regenerated — and converges
     the dates users browse within hours; deep history grinds for days behind the
     scenes (≈8 min / 16 GiB per day, resumable). Pause chunks over the 17:00Z/20:15Z
     cron windows unless the node fits two ~16 GiB fits at once.
  4. Web/API work may continue throughout (separate pods; the backfill only talks to
     postgres). Do not run DB migrations or restart `postgres-0` mid-backfill. Ship
     the API stitch deletion (removing 0132's fallback) any time after the backfill
     has passed the dates users can reach.
  5. Last, after the full span is regenerated: re-materialize `analysis_grade_daily`
     (`materialize_brief_grade`) and rerun `load_scoreboard`. On-the-fly grade
     endpoints will drift day-by-day during the backfill as history flips to the new
     cut — expected, self-resolving.
* Record before/after grade deltas in the run log: evening-hour grades are expected to
  *worsen* slightly — that is the leak being removed, not a regression.
* **Vintage-faithful preview backfill**: a backfilled h2 with the plain DAM-close
  cutoff would read covariate vintages ~19h fresher than the live 15:15 CT D−2 run
  could see (one daily load/wind/solar snapshot, ~19h of outage snapshots),
  collapsing the preview into a re-labeled final. The vintage history is append-only
  (`posted_datetime` in every PK; load/wind/solar 1 snapshot/day at ~09:30–09:55 CT
  since 2024-04-14, `outages_zonal` ~21/day since 2024-01-01), so faithfulness is a
  query matter: thread a `vintage_cutoff` (the run's fire instant) through the four
  vintaged reads in `compute/mu/features.py` (`load_forecast_zonal`,
  `wind_forecast_regional`, `solar_forecast_regional`, `outages_zonal`), making the
  predicate `posted_datetime <= LEAST(dam_close(interval), vintage_cutoff)`.
  The h2 backfill passes each day's historical fire instant (20:15Z on D−2, the cron
  schedule); h1 passes its fire time (17:00Z on D−1 — after DAM close, so a no-op
  that keeps one code path). Live runs pass their own fire time, which also makes
  future h2 emissions and h2 backfills byte-identical by construction. This keeps
  the preview track one continuous, honestly-disadvantaged series across the re-cut.
* Do NOT touch: DB storage timezone (UTC instants stay), ingest jobs, `forecast_nodal`
  / `forecast_sf_artifact` schemas or keys.

## Acceptance

* [ ] Every re-backfilled `(run_id, delivery_date, horizon)` spans exactly
      `delivery_bounds(delivery_date)`: 05:00Z→04:00Z+1 in CDT, 06:00Z→05:00Z+1 in CST,
      23/24/25 distinct hours matching the CT calendar.
* [ ] No train window contains any interval of its scored CT day (test asserts the cut
      at CT midnight, including both DST transition days).
* [ ] Brief t+1 renders fully at ~17:05Z and t+2 at ~20:20Z from single artifacts; no
      request loads two artifacts for one day.
* [ ] 0132's partial-coverage fields and fallback paths are deleted; API tests updated.
* [ ] `analysis_grade_daily` and scoreboards regenerated over the full span; run log
      records the grade delta attributable to the evening-hour fix.
* [ ] Regenerated h2 rows carry covariate vintages a live run could have seen: every
      `vintage_load`/`vintage_wind`/`vintage_solar`/`vintage_outage` ≤ that day's
      20:15Z D−2 fire instant (spot-check against the 18 live-emitted days before
      overwriting them). h1 rows are unchanged by the cutoff cap (no-op assertion).
* [ ] A backtest fold and a served day with the same D produce identically-phased
      train/score windows.
