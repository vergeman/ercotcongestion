# 0127 - dam-daily-settle-and-coverage-guards

Type: fix
Branch: fix/0127-dam-daily-settle-and-coverage-guards

## Goal

* Move `dam_shadow` and `dam_lambda` onto the daily-settled ingest path so they stop re-pulling every cycle and grab the next operating day by name at DAM close.
* Guard `_load_dam` and the horizon-2 preview gate so a partial (stray-tail) shadow-price window can't produce a misleading `after_action` or false-pass the gate.

## Context

* `dam_shadow`/`dam_lambda` ride the rolling 2h window, which filters by `deliveryDate` derived from the UTC clock — so they only reach tomorrow's label after the clock rolls (19:00 CT), a full operating day behind `dam_spp` (the only `daily_settled` endpoint). This left op-day 7/30 shadow prices uningested at forecast time.
* A UTC delivery day spans two CT op-days, so its window always catches ~5 tail hours of the prior op-day's shadow report. That partial tail made `_load_dam` return non-`None` (`after_action=True` on near-empty data) and false-passed the h2 gate (`LIMIT 1` matched the tail).
* daily-settle is the primary fix (data lands on time); the coverage guards are defense-in-depth for a late ERCOT post or ingest hiccup.

## Approach

* Work in: `ercot_ingest/backfill.py`, `compute/jobs/daily_brief.py`, `compute/jobs/daily_forecast.py`
* Add `"daily_settled": True` to the `dam_shadow` and `dam_lambda` `ENDPOINTS` entries. `DAILY_SETTLED` auto-derives, so `update_recent_window` skips them on the rolling pass and `update_recent_daily` pulls them by delivery-date name (throttled by `is_completed`, D+1 after 14:00 CT). Add a one-line comment on each entry mirroring `dam_spp`'s rationale.
* `daily_brief.py:_load_dam` — replace `if M.empty or C.empty` with a window-coverage check: require the shadow-price panel `M` to span the delivery window (its interval coverage reaches the final hours of `[D, D+1)`, not just be non-empty). Below the floor → return `None` (F6 stays off; the grade tick re-briefs once DAM fully lands). Keep the `C.empty` check.
* `daily_forecast.py:_assert_freshest_history_published` — replace the `LIMIT 1` existence check with the same coverage floor over D−1's window; still `raise` (fail-loud, nothing written) when short.
* Factor the coverage predicate once (small shared helper) so the brief and the gate apply the identical rule.
* Nudge the h2 preview cron so it fires after the 14:00 CT daily-settle fetch in both DST seasons (else the now-strict gate could block a winter preview whose DAM is published but not yet ingested).
* Do NOT touch: `dam_spp` config; the rolling-window path for other endpoints; the forecast/fit path; the ingest CronJob (its command is unchanged).

## Acceptance

* [x] `dam_shadow`/`dam_lambda` appear in `DAILY_SETTLED` and are dropped from the rolling pass (`update_recent_window` skips them → `update_recent_daily` requests D+1 by name after 14:00 CT, `is_completed`-throttled). — verified `DAILY_SETTLED == ('dam_spp','dam_shadow','dam_lambda')` in-container.
* [x] `_load_dam` returns `None` when the shadow window is only the ~5h prior-op-day tail (→ `after_action=False`), and returns the panel for a fully-ingested day (6/30 → `after_action=True`, unchanged). — predicate unit test + live 6/30 dry-run.
* [x] The h2 gate raises on a D−1 window that is only the partial tail; passes when it spans the window — both call `dam_shadow_covers_window`. — code + predicate unit test.
* [x] Coverage predicate is shared by both call sites (one definition in `compute/sf/panels.py`). — import-identity check.
* [x] Existing tests pass and a fully-ingested day is unchanged. — 86 passed (`sf/tests` + `analysis/tests`, incl. new `test_dam_coverage.py`); 6/30 brief still `after_action=True`.

### As-built notes

* Predicate + threshold live in `compute/sf/panels.py` (`dam_shadow_covers_window`, `DAM_SHADOW_MIN_COVER_HOURS = 12`) — both jobs already import from there, so no cross-job coupling. 12h clears the ~4h tail with margin below a normal day's ~23h afternoon-peak max; erring to "not covered" is the safe side.
* Cron nudge (`forecast_preview_cronjob.yml`): `45 19 * * *` → `15 20 * * *` (20:15 UTC = 15:15 CDT / 14:15 CST), still 3h+ clear of the 17:00 UTC final tick.
* Guards verified by the shared predicate's unit tests, not a live partial-DAM day (dev DB holds only the fully-ingested 6/30 artifact).
