# 0122 - forecast-day-boundary-and-labeling-fixes

Type: fix
Branch: fix/0122-forecast-day-boundary-and-labeling-fixes

## Goal

* Make `--delivery-date tomorrow` resolve unambiguously so a manual evening run cannot silently produce the wrong day.
* Backfill the missing forecast for UTC delivery day 2026-07-27 (currently zero rows in prod).
* Record, once, that run time has no bearing on `forecast_day`'s output, so the "should it refuse to run late?" question stops recurring.
* Correct the `api/forecast.py` window comment, which currently asserts the opposite of what the code does.
* Narrow the `dam_spp` ingest to the delivery days it actually needs instead of re-pulling whole days every 15 minutes.
* Label the scrubber with the delivery-hour span (CT) and the forecast run that produced it.

## Context

* The forecast day is a **UTC** calendar day: `forward_hours = pd.date_range(D, periods=24, freq="h", tz="UTC")` (`compute/jobs/daily_forecast.py:272`). UTC midnight is 19:00 CT the prior evening (CDT) / 18:00 CT (CST), so `delivery_date=2026-07-26` covers CT Jul 25 19:00 → Jul 26 18:00 — verified in prod.
* `tomorrow` resolves off the UTC clock (`daily_forecast.py:363`). A hand-run at `2026-07-27T01:10:32Z` (20:10 CT Jul 26) resolved to July **28**, skipping July 27 entirely and flipping `forecast_current` anyway. Silent: exit 0, valid 24h panel, no warning. The default landing view serves `MAX(delivery_date)` (`api/forecast.py:116-118`), so the hole is invisible until someone scrubs onto it.
* The job's validity depends on a ~90-minute margin: covariates are pinned to DAM close (10:00 CT, `features.py:63`) so it cannot run earlier, and ERCOT publishes DAM results for delivery day D by 13:30 CT on D-1 so it must not run later. Cron at 17:00 UTC (12:00 CDT / 11:00 CST) sits inside that box. `forecast_cronjob.yml:33` currently invites pushing it later with no stated ceiling.
* **Not doing CT-day realignment in this plan** (see Deferred below). Rescheduling the cron does *not* fix alignment — the block boundary comes from `D`, not from run time.

## Approach

* Work in: `compute/jobs/daily_forecast.py`, `ercot_ingest/backfill.py`, `api/forecast.py`, `ops/deploy/jobs/forecast_cronjob.yml`, `web/src/components/playback/`
* Entry point / primary change: `_resolve_delivery_date` in `compute/jobs/daily_forecast.py:360`

### 1. `tomorrow` resolution (fix + guard)

* In `_resolve_delivery_date`, compute the candidate from **CT** wall-clock, not UTC: take `now` in `America/Chicago`, add one day, and map that CT date to its UTC-day label. This makes "tomorrow" mean what an operator standing in Texas means.
* Log the resolved date at INFO **with its CT hour span** — e.g. `delivery_date=2026-07-27 (CT 2026-07-26 19:00 → 2026-07-27 18:00)`. This single line would have made the skip self-evident.
* Refuse to overwrite an existing `(run_id, delivery_date)` in `forecast_nodal` unless `--force` is passed. Today the write is replace-in-place (`daily_forecast.py:322-323`) with no confirmation.

### 2. Backfill the July 27 hole

* Run the documented single-day path from `forecast_cronjob.yml:7-14` with `--delivery-date 2026-07-27 --run-id mu-all-v1 --to-db`.
* Causally safe despite July 27's DAM now being in the DB: `load_shadow_prices` / `load_congestion_panel` read `interval_ts >= start AND interval_ts < end` with `end = D` (`compute/sf/panels.py:36`, `:160`), so the fit cannot see the day it predicts.
* Verify afterward that `forecast_nodal` has no gaps in `delivery_date` across the last 14 days.

### 3. Timeliness — document, do not guard

* **No ceiling.** A guard was built and removed: run time does not enter the computation. Covariates are filtered on `posted_datetime <= dam_close(interval_ts)` (`features.py`); shadow prices / congestion are bounded by `interval_ts < D` (`panels.py:81`, `:161`), which is what excludes D's own prices — structurally, not by timing; the SF window closes at `≤ D` and the residual pool is `week < D`. A run at 16:00 CT yields the same panel as one at 12:00 CT, and a backfill reproduces the day it would have produced live. A hard fail would have converted a delayed pod into a missing delivery day — the exact failure class this plan exists to close.
* Only the **floor** binds: 10:00 CT on D-1 (DAM close). Earlier has nothing to read and already fails loud.
* Add a short "Run time does not affect the output" note to `compute/README.md` step 6 and point `forecast_cronjob.yml` at it, so the next reader does not re-derive this.

### 4. Correct the wrong comment

* `api/forecast.py:105-107` claims the default window is taken from stored rows so "the CT operating day and its DST offset come from the stored rows rather than UTC-midnight arithmetic on the client." The stored rows *are* UTC-midnight arithmetic (`daily_forecast.py:271`). Replace with an accurate description: the window is the UTC-day span of the run's latest `delivery_date`, which in CT runs 19:00 → 18:00.

### 5. Narrow the `dam_spp` ingest

* `dam_spp` uses `param_format: "date"` and date filters are whole-day inclusive (`ercot_ingest/backfill.py:183-188`), so each 15-min tick re-pulls entire delivery days — 26,736 rows (1114 SPs x 24h), ~96 times a day. Correct via upsert, just wasteful.
* Keep the whole-day semantics (they are what makes a straddling window pick up the next delivery date at all — this is how tomorrow's DAM legitimately lands), but skip the fetch when the target delivery days are already complete for the expected SP count. Reuse the self-throttling `ingest_log` lookup pattern already used by `backfill_dam_close.update_recent` / `backfill_outages.update_recent`.
* Do NOT change the date-label derivation itself — narrowing it would stop tomorrow's DAM from being ingested.

### 6. Scrubber label

* Prefix the cursor timestamp with what the axis *is*: `Delivery hour: Jul 27, 2026 02:00 CT`. The label sits inside the timestamp span so it inherits that face, size and color — one string, not a chip beside one.
* Hover carries the distinction that caused the confusion: "The hourly settlement price power is priced **for**."
* Render CT via `formatCT` (`web/src/lib/time.ts:8`); sentence case per the `.label` rule in `index.css`; do not uppercase dynamic values.
* **Not** the window span or `run_id`: the span is already on the timeline's end labels and the model is already in the Stats panel.

* Do NOT touch: CT-day realignment of the forecast block; the vantage/as-of axis; forecast vintage storage; the SP-universe drift.

## Acceptance

* [x] `_resolve_delivery_date("tomorrow")` returns the same delivery day whether invoked at 09:00 CT or 22:00 CT on the same CT date; unit test covers six hours across four dates, including both DST transitions.
* [x] Job logs one INFO line naming the resolved `delivery_date` and its CT hour span.
* [x] Re-running an existing `(run_id, delivery_date)` without `--force` exits non-zero without writing or flipping `forecast_current` — checked *before* the fit, so it costs a query rather than 20 minutes.
* [x] `forecast_nodal` has rows for `delivery_date = 2026-07-27`, run_id `mu-all-v1`, 24 distinct `ts`, and no gaps across the trailing 14 days. Verified in prod: 26,760 rows `00:00Z → 23:00Z` + its SF+μ artifact; `mu-all-v1` is contiguous over all 574 days.
* [x] `compute/README.md` states that run time does not affect the output, with the two mechanisms (vintage predicate, interval bound) named; `forecast_cronjob.yml` points at it instead of advising a schedule change.
* [x] `api/forecast.py` window comment describes UTC-day derivation and its CT span; no reference to recovering a CT operating day. "Operating day" also replaced on the OpenAPI surface, where it asserted the same wrong thing.
* [x] A 15-min ingest tick with all target delivery days already complete performs no `dam_spp` fetch and logs the skip; a tick where tomorrow's DAM has just published still ingests it.
* [x] Scrubber reads `Delivery hour: <cursor> CT` in the timestamp's own face, with the priced-for distinction on hover.

## Notes from execution

* The `ercot-forecast` CronJob was created `2026-07-27T01:05:22Z` and had **never fired on schedule** (`LAST SCHEDULE <none>`). Days through 07-26 came from the bulk backfill; the only forecast run was the 01:10:32Z hand-run that jumped to 07-28. So 07-27 was never produced by anything, and no later tick would have produced it either.
* 07-28's rows were deleted after the backfill so the first scheduled tick writes that day itself. The landing view (`MAX(delivery_date)`) is 07-27 until then.
* Pre-existing, untouched: a few partial days in the bulk-seeded history at DST / weekly-window boundaries (`2025-11-02` 23h, `2026-03-07` 6h + `2026-03-08` 18h), and `2026-04-12` has nodal rows with no SF artifact.
