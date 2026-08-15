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
  1. Ship `0132-brief-day-stitch-tail` first *(done — #203)*: with the D+1 artifact
     optional, a new-cut day rendered fully through the *old* API path (concat +
     dedupe + CT-window filter already covered it), so the cron cutover needed no
     synchronized API deploy.
  2. Deploy the new compute image to `ercot-forecast` / `ercot-forecast-preview` and
     let them run — no suspension. Overwrites are keyed by
     `(run_id, delivery_date, horizon)` and `forecast_day` is deterministic, so a day
     emitted live and later re-backfilled converges to the same artifact (h2 included:
     the fire-time vintage cap uses the same historical instant either way).
  3. Backfill the artifact, per horizon, **newest chunks first** (reverse date order):
     h2 2026-07-30→present, then h1 in reverse chunks back to 2025-01-01.
     `--no-skip-existing` is required — every historical day already carries an
     *old*-cut artifact, so without it the skip-existing check skips everything.
     Newest-first heals the one **seam day** quickly — the last old-cut day's CT
     evening exists in neither artifact until that day is regenerated — and converges
     the dates users browse within hours; deep history grinds for days behind the
     scenes (≈8 min / 16 GiB per day, resumable; memory doesn't stack across days, so
     chunk size is a monitoring/cron-collision choice, not a hard limit — ~7–14 days
     per invocation near the dates users browse, larger once past that). Pause chunks
     over the 17:00Z/20:15Z cron windows unless the node fits two ~16 GiB fits at once.

     ```
     nohup python ... > /compute/runs/backfill.log 2>&1 </dev/null &

     # h2 (preview) — the small track, do it first
     python -m compute.jobs.backfill_artifacts --run-id mu-all-v1 --map-run-id map-v1 \
         --horizon 2 --no-skip-existing --to-db \
         --start 2026-07-30 --end 2026-08-14

     # h1 (final) — reverse chunks back to 2025-01-01, newest first
     python -m compute.jobs.backfill_artifacts --run-id mu-all-v1 --map-run-id map-v1 \
         --horizon 1 --no-skip-existing --to-db \
         --start 2026-08-01 --end 2026-08-14

     # h1 continuation
     python -m compute.jobs.backfill_artifacts --run-id mu-all-v1 --map-run-id map-v1 \
         --horizon 1 --no-skip-existing --to-db \
         --start 2026-07-18 --end 2026-07-31
     # ...continue in reverse-date chunks back to --start 2025-01-01
     ```

  4. Roll up each freshly-backfilled range into queryable constraint history — same
     `run_id`/horizon/date range as step 3, run right behind it. This job only
     decodes `forecast_sf_artifact` (never refits), so it is cheap and fast; without
     it the constraint-explorer panel (`/map/constraints/ranked`) keeps showing
     pre-0133 history for any day step 3 already re-backfilled. Not called out in
     earlier drafts of this runbook — added here because it is a real dependency.

     ```
     python -m compute.jobs.backfill_forecast_history --run-id mu-all-v1 --to-db \
         --horizon 2 --start 2026-07-30 --end 2026-08-14
     python -m compute.jobs.backfill_forecast_history --run-id mu-all-v1 --to-db \
         --horizon 1 --start 2026-08-01 --end 2026-08-14
     # ...same chunk boundaries as step 3, horizon 1
     ```

  5. Web/API work may continue throughout (separate pods; the backfill only talks to
     postgres). Do not run DB migrations or restart `postgres-0` mid-backfill. The
     API stitch deletion (removing 0132's fallback) *(done — this branch)* is safe to
     ship any time after the backfill (steps 3–4) has passed the dates users can
     reach; shipping it earlier would 404 pages for days not yet re-backfilled.
  6. Last, after the full span (steps 3–4) is regenerated: re-materialize
     `analysis_grade_daily` via `materialize_brief_grade`, in 30-day batches ending at
     the newest settled day and walking backward — the job counts days *backward*
     from `--delivery-date`, so move the end date back exactly `--days` each batch
     (its own docstring has the worked example):

     ```
     python -m compute.jobs.materialize_brief_grade \
         --run-id mu-all-v1 --horizon 1 --delivery-date 2026-08-14 --days 30
     python -m compute.jobs.materialize_brief_grade \
         --run-id mu-all-v1 --horizon 1 --delivery-date 2026-07-15 --days 30
     # ...continue back to 2025-01-01; repeat the same batches with --horizon 2
     # for the ~18 h2 days (2026-07-30→present)
     ```

     `load_scoreboard` (→ `scoreboard_weekly`) transcribes the **offline backtest's**
     `mu_score_weekly.csv`/`mu_bands_weekly.csv` — it never reads `forecast_nodal` or
     `forecast_sf_artifact`, so rerunning it (`python -m compute.jobs.load_scoreboard
     --run-id mu-all-v1`) picks up nothing from this backfill unless the backtest
     walk is also re-run (out of scope here). Treat it as optional hygiene, not a
     dependency of this rollout.

     `scoreboard_daily` (the **live** per-day board, `grade_day.py`) has no bulk
     date-range CLI — only `--delivery-date auto|YYYY-MM-DD`, one day at a time — and
     nothing above refreshes its history. Decide deliberately whether stale
     pre-0133 historical rows there are acceptable (it is framed as a forward-looking
     live metric that grades "yesterday" each tick, not an archive) rather than
     assuming; if not, each historical day needs its own
     `python -m compute.jobs.grade_day --run-id mu-all-v1 --horizon <1|2>
     --delivery-date <YYYY-MM-DD> --to-db`.

     On-the-fly grade endpoints will drift day-by-day during the backfill as history
     flips to the new cut — expected, self-resolving.
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
      23/24/25 distinct hours matching the CT calendar. Code path ready
      (`daily_forecast.forecast_day` builds `forward_hours` from `ct_day_bounds`,
      `backfill_artifacts.py` supports `--horizon`); the runbook backfill itself
      (step 3) has not been run yet — nothing re-backfilled on prod so far.
* [x] No train window contains any interval of its scored CT day (test asserts the cut
      at CT midnight, including both DST transition days). `predict_day`'s CT anchor
      + `test_predict_day_score_block_is_dst_aware`/`test_score_block_is_dst_aware`
      (spring-forward 23h, fall-back 25h) plus
      `test_reads_and_propagation_touch_no_interval_at_or_after_D` pin this.
* [ ] Brief t+1 renders fully at ~17:05Z and t+2 at ~20:20Z from single artifacts; no
      request loads two artifacts for one day. The "no request loads two artifacts"
      half is true by construction now (`load_daily_artifact_tail` deleted, every
      API path reads one `load_daily_artifact` call) — but this line is really a
      claim about the live cron's timing once deployed (runbook step 2), not yet
      observed in prod.
* [x] 0132's partial-coverage fields and fallback paths are deleted; API tests updated.
      `ArtifactTail`/`load_daily_artifact_tail`/`StitchedProfile` and every
      `tail_horizon`/`hours_covered`/`hours_expected` field removed from
      `api/services/sf_artifacts.py`, `api/analysis.py`, `api/models.py`,
      `web/src/api/types.ts`, `web/src/pages/BriefPage.tsx`; `get_hero_latest`'s
      D+1 `EXISTS` join simplified too (a third stitch site the plan didn't
      originally name). Tests updated in `api/tests/test_analysis.py` and
      `api/tests/test_sf_artifacts.py`.
* [ ] `analysis_grade_daily` and scoreboards regenerated over the full span; run log
      records the grade delta attributable to the evening-hour fix. Not started —
      runbook step 5, gated on the backfill (step 3) completing first.
* [ ] Regenerated h2 rows carry covariate vintages a live run could have seen: every
      `vintage_load`/`vintage_wind`/`vintage_solar`/`vintage_outage` ≤ that day's
      20:15Z D−2 fire instant (spot-check against the 18 live-emitted days before
      overwriting them). h1 rows are unchanged by the cutoff cap (no-op assertion).
      Code path ready (`vintage_cutoff`/`LEAST(...)` threaded through all four
      vintaged reads in `features.py`, verified against real dev-DB rows; h1/h2
      fire-time computation unit-tested in `test_backfill_artifacts.py`) — the
      actual regenerated rows and live-day spot-check don't exist until the
      backfill (step 3) runs.
* [x] A backtest fold and a served day with the same D produce identically-phased
      train/score windows. `predict_day`'s CT-midnight re-anchor plus the CLI's
      `score_from_ts` tz fix (was `tz="UTC"` against the read-floor's
      `tz="America/Chicago"` for the same `origin` string — a real desync);
      `test_predict_day_reconciles_with_walk_forward` now pins bit-identical
      output at a real CT-midnight `D` passed as `score_from` to both.
