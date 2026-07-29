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
* Do NOT touch: `dam_spp` config; the rolling-window path for other endpoints; the forecast/fit path; k8s manifests (the ingest CronJob command is unchanged).

## Acceptance

* [ ] `dam_shadow`/`dam_lambda` appear in `DAILY_SETTLED`; a live cycle logs them under the "already complete — no fetch" throttle instead of re-fetching each tick, and requests D+1 by name after 14:00 CT.
* [ ] `_load_dam` returns `None` for a day whose shadow window is only the ~5-hour prior-op-day tail (→ `after_action=False`), and returns the panel once the full operating day is ingested.
* [ ] The h2 gate raises on a D−1 window that is only the partial tail; passes when D−1's shadow prices fully cover the window.
* [ ] Coverage predicate is shared by both call sites (one definition).
* [ ] Existing `compute/analysis/tests` + `daily_brief` behavior unchanged for a fully-ingested day (byte-identical brief).
