# 0123 - forecast-horizon-preview

Type: feat
Branch: feat/0123-forecast-horizon-preview

## Goal

* Add a t+2 "preview" forecast run: same model (`run_id` unchanged — it scopes
  model version only), run after day T+1's DAM publishes (~13:30 CT), forecasting
  delivery day T+2 with ~20 h of lead before that day's DAM closes.
* Persist preview (horizon=2) and final (horizon=1) rows side by side per
  `(run_id, delivery_date)` — the noon t+1 run never overwrites the preview, so
  `final − preview` is a preserved audit trail (the effect of overnight
  load/wind/solar/weather vintage revisions on an otherwise identical model).
* Serve one continuous series with zero web changes: the API coalesces per
  delivery day (prefer horizon 1, fall back to 2) and reports per-day horizon
  provenance; grade each horizon as its own scoreboard track.

## Context

* The 12:00 CT t+1 run fires two hours after D's DAM already closed — it is
  verification-only, never actionable. A t+2 run lands inside the decision
  window. See `docs/daily_brief_engine.md` §"Timing and the t+2 horizon".
* No new data is needed: the fitted heads are identical at both horizons (all
  train rows publish before either run); only the vintaged forecast covariates
  on the prediction row differ (`features.py` `posted_datetime <= dam_close(D)`
  resolves to "newest existing" when the pin is in the future — admissible by
  construction).
* `run_id` must keep meaning MODEL VERSION (spec §4, `daily_forecast.py`).
  Horizon is a property of the run instance, so it becomes a column, not a
  run_id suffix. Uniqueness everywhere widens from `(run_id, delivery_date)` to
  `(run_id, delivery_date, horizon)`.
* Contract: horizon-2 rows are immutable once written — never deleted by the
  noon run, never served by default once horizon 1 exists for the day.
* One silent failure mode to guard: a t+2 run fired before day T+1's DAM
  publishes (late ERCOT post) would quietly fit with its freshest history day
  missing. Must fail loud, prior rows intact.

## Approach

### Commit 1 — migration: the horizon column

* Work in: `db/migrations/37_forecast_horizon.sql`
* Add `horizon smallint NOT NULL DEFAULT 1` (1 = final/t+1, 2 = preview/t+2)
  to `forecast_nodal`, `forecast_sf_artifact`, `scoreboard_daily`.
* Replace each table's `(run_id, delivery_date, …)` unique constraint/index
  with one including `horizon` (existing rows backfill to 1 via the default —
  no data rewrite).
* `CHECK (horizon IN (1, 2))`.

### Commit 2 — write-path plumbing (compute writers)

* Work in: `compute/jobs/backfill_nodal.py`, `compute/jobs/grade_day.py`
* `nodal_to_db(..., horizon: int = 1)` — the delete-then-COPY scope becomes
  `(run_id, delivery_date, horizon)`; COPY includes the column.
* `persist_sf_mu_artifact(..., horizon: int = 1)` — upsert key widens the same
  way; the npz filename gains a `_h2` suffix only for horizon 2 so horizon-1
  disk artifacts keep their current names.
* `grade_day(..., horizon=1)` reads the horizon's own rows;
  `persist_grades`/`resolve_gradeable_date` scope to `(run_id, horizon)` — two
  independent scoreboard tracks per run_id.
* Backfill CLI paths default to horizon 1 and are otherwise untouched.
* Do NOT touch: `forecast_current` pointer semantics (single pointer, unchanged).

### Commit 3 — daily_forecast: `--horizon 2`, date resolution, DAM gate

* Work in: `compute/jobs/daily_forecast.py`
* Add `--horizon {1,2}` (default 1). Thread through `ForecastResult`,
  `persist_forecast`, `_day_already_published` (scoped so the preview's
  existence never blocks the noon run and vice versa), and the run-log lines.
* `_resolve_delivery_date`: with horizon 2, `tomorrow` resolves to the CT date
  + 2 days (same CT-clock rule; explicit `YYYY-MM-DD` unchanged).
* DAM-publication gate, horizon 2 only, before the fit: assert
  `ercot_dam_shadow_prices` has rows covering delivery day D−1 (the freshest
  history day). Missing → RuntimeError, nothing written (spec §8 pattern).
* Horizon 2 publish runs `--no-grade` semantics by default? No — grading is
  horizon-scoped (commit 2), so the h2 tick grades the h2 track; keep the flag
  as-is.
* Record `map_run_id` + SF window used in the run log so preview-vs-final
  diffs contaminated by a weekly map refit are identifiable.
* Do NOT touch: the fit path (`forecast_day` stages 1–2 compute identically at
  both horizons — horizon is persistence/labeling only).

### Commit 4 — API + web: per-day coalesce, provenance, preview badge

* Work in: `api/forecast.py`, `api/services/sf_artifacts.py` (callers in
  `api/map.py`, `api/matrix.py` follow through the service), `web/src/`
* Range query: fetch both horizons for the resolved run_id; pick per
  delivery day by `ORDER BY horizon ASC` (prefer final, else preview) — one
  continuous series, same response shape.
* Response provenance: per-day horizon map (e.g.
  `"horizons": {"2026-08-01": 2, …}`) alongside the existing `run_id`.
* Per-day artifact lookup (`sf_artifacts`): try `(run_id, date, horizon=1)`,
  fall back to `horizon=2`; cache key includes horizon.
* Optional `?horizon=` query param to explicitly read the preserved preview for
  a day that already has a final (the "what changed" view). Explicit horizon
  with no rows → 404, no fallback.
* Web: render a "PREVIEW — refreshes at noon CT" badge when the selected day's
  provenance is horizon 2. Read-only off the per-day horizon map; no toggle, no
  fetch changes — the scrubber still renders the one coalesced series. Use the
  existing `--track-label` token convention for the badge label (static string,
  never uppercase a dynamic value).

### Commit 5 — ops: the second daily tick + runbook

* Work in: `ops/deploy` (cron/job manifests), runbook docs
* Add the h2 tick at ~19:45 UTC (≈14:45 CT, after the ~13:30 CT DAM post; gate
  from commit 3 backstops a late post) running
  `daily_forecast --delivery-date tomorrow --horizon 2 --run-id <current> --to-db`.
* Keep the 17:00 UTC horizon-1 tick unchanged. Sequential, never concurrent —
  each fit needs most of the 16 Gi node.
* Runbook: the two-track table (which tick, which horizon, gate behavior,
  immutability contract), logging reminders per repo convention.

## Acceptance

* [x] Migration 37 applies on a copy of prod; existing rows read back as
      horizon 1; all current API queries return identical results pre/post.
      — Applied on the dev DB (8.4M nodal rows backfilled to h1); widened PKs +
      CHECK verified; re-apply idempotent.
* [x] `daily_forecast --horizon 2 --delivery-date tomorrow` resolves to CT
      today + 2 days and refuses to run (non-zero, nothing written) when day
      D−1 has no shadow-price rows.
      — Verified live (exit 1, gate message, zero rows written) + unit tests
      across both DST transitions.
* [x] Running h2 for day X then h1 for day X leaves BOTH row sets present;
      re-running h1 replaces only horizon-1 rows (preview bytes unchanged).
      — DB-backed `test_horizon_tracks_coexist_and_final_never_clobbers_preview`
      + direct writer check.
* [x] Range API over a week of 5 final + 1 preview-only days returns one
      gapless series; the preview day's rows come from horizon 2 and the
      provenance map says so; the day after the noon run lands, the same
      request serves horizon 1 for that day with no other change.
      — Verified against the running API with seeded h1/h2 rows + `test_forecast.py`.
* [x] `?horizon=2` returns the preserved preview for a day that has both;
      `?horizon=1` on a preview-only day 404s.
      — Verified live + unit tests.
* [x] `scoreboard_daily` carries separate rows per horizon; grading tick for
      each track selects only its own ungraded days.
      — `grade_day`/`persist_grades`/`resolve_gradeable_date` scoped to
      `(run_id, horizon)`; `test_grade_day.py` horizon cases.
* [x] Matrix/map artifact lookup for a preview-only day serves the h2 artifact;
      after the final lands, the same request serves h1.
      — `load_daily_artifact` coalesce (min-horizon probe before cache);
      `test_sf_artifacts.py` coalesce/fallback/independent-cache cases.
* [x] Web shows the preview badge on a horizon-2 day and no badge on a
      horizon-1 day; nothing else in the UI changes.
      — Read-only off the per-day `horizons` map (`getForecastHorizon` →
      `isPreviewDay` badge); tsc + vite build clean. Build-verified, not
      screenshotted (no preview-only day in the served dev run).
* [x] Run log lines include horizon, CT span, and `map_run_id`/SF window.
      — `forecast_day` opening line + `_summary` carry horizon, CT span,
      `map_run_id`, SF `window_end`.
