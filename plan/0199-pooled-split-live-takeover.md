# 0199 - pooled-split-live-takeover

Type: feat
Branch: feat/0199-pooled-split-live-takeover

## Goal

* Extend the pooled pre/post-RTC+B split table so live daily final grades take over past the backtest's last week.
* Combine per-week backtest scores with per-day live scores by n_hours weight, so recent live days don't outweigh the backtest record.
* Split label shows the live extension (e.g. `Post-RTC+B · 32w + 45d`).
* Rename the panel "Track record · pooled pre/post-RTC+B" (no longer backtest-only).

## Context

* `scoreboard_weekly` was a one-time backtest catch-up, never maintained — it ends 2026-07-15, ~7 weeks stale. Live daily grades (`scoreboard_daily`, horizon=1) carry the record forward from 2026-07-18 with the same metrics.
* The track-record graph already does this takeover: `build_history` unions `backtest_weekly` + `served_daily` points at a boundary date (plan 0177). The pooled split table never opted in.
* Weekly and daily share the same four series (model/persistence/climatology/oracle) and the same three metrics at nodal granularity; only the source-id strings and cadence differ. All live data is post-RTC+B, so `pre_rtc_b` is untouched.
* Reuse surface in `scoreboard.py`: the latest-h1-final-rows fetch is duplicated in `build_history` (inline) and the split needs the same rows — extract one shared helper. The only pooling helper is `_mean` (equal-weight), with a single caller; no n_hours-weighted mean exists yet.

## Approach

* Work in: `api/services/scoreboard.py` (pooling), `api/schemas/scoreboard.py` (add `n_days`), `web/src/pages/ScoreboardPage.tsx` + `web/src/api/types.ts` (label + heading).
* Entry point: `_build_splits` / `_pooled_source`.
* Reuse the daily fetch: extract `_latest_final_daily_rows(cur)` (soft — returns `run_id | None` and all latest-h1 rows, tolerates empty) from `build_history`'s inline query, and call it from both `build_history` and `build_weekly`/`_build_splits`. `build_latest_final_daily` is a different shape (single latest day + `horizon`) — leave it.
* Reuse the pooling helper: swap `_pooled_source` from `_mean` to a new `_wmean(rows, key)` (n_hours-weighted; a week counts ~7x a day). Remove `_mean` — `_pooled_source` is its only caller. This averages period-level scores; it does not recompute a pooled score from raw pairs (the backtest CSV only kept per-week values).
* Normalize both cadences to one row set: remap each daily row to the *weekly* source id sharing its series (via `_DAILY_BY_ID[...].series_id`, same lookup `build_history` uses) so the columns line up; carry `period` (week or delivery_date), `n_hours`, and `cadence`.
* Add `n_days` to `WeeklySplit`; render `· {n_weeks}w` plus `+ {n_days}d` when > 0.
* Rename the panel: heading `Track record · pooled pre/post-RTC+B ({metric})` (drop "Backtest"). Keep `SPLIT_LABELS` (`All weeks` / `Pre-RTC+B` / `Post-RTC+B`); note in the top-of-file comment and tooltip that each cell is an independent hours-weighted pool, "All weeks" spans all time (not the average of the two cells), Pre-RTC+B is backtest-only, Post-RTC+B blends backtest weeks + live days.
* Do NOT touch: `scoreboard_weekly`/`scoreboard_daily` tables, the backfill job, the graph's rendering, or `build_latest_final_daily`.

## Acceptance

* [x] Post-RTC+B and All splits reflect live days through the latest final grade; Pre-RTC+B unchanged.
* [x] Pooled values are n_hours-weighted; a handful of live days does not swing the post-RTC+B number more than their hours warrant.
* [x] Split label shows weeks and live days separately.
* [x] Panel is titled "Track record · pooled pre/post-RTC+B"; no wording implies backtest-only.
* [x] Comment/tooltip states cells are independent hours-weighted pools and "All weeks" is not the average of pre/post.
* [x] `beats_persistence` recomputes on the combined record.
* [x] `_latest_final_daily_rows` is the single fetch shared by `build_history` and the split; `_mean` is gone (no dead code).
* [x] Existing scoreboard tests pass; a test covers the weekly+daily n_hours-weighted pooling.
