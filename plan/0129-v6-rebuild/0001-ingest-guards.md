# 0129-0001 - ingest-guards

Type: fix
Branch: fix/0129-0001-ingest-guards
Depends on: none — start here

## Goal

* **Unstall `load_by_zone`, stopped at 2026-07-22 — the one real defect here.** Root
  cause is confirmed a **live-scheduling gap against a lagging report**, not a retired
  endpoint (see Context): NP6-345-CD still serves every missing day (2026-07-23 →
  ~D−2) on the same path, but the live loop only ever asks for *today* (always empty
  for a report that publishes ~2 days late) and never re-fetches a day once it lands.
  Fix = give `loads` a multi-day per-day lookback like the DAM endpoints, plus a
  one-time backfill of the gap.
* Pin a regression test that keeps the NaN `gen_*` guard (`_f`) from being dropped.
  **The rows themselves are already clean** — a prod scan (`WHERE gen_x <> gen_x`
  over every numeric column of both `wind_hourly_regional` and
  `solar_hourly_regional`) returns 0 cells, and the three DST days are intact and
  NaN-free. The pre-`_f` damage was already repaired by a re-ingest; only the
  regression test remains.

### Not a defect (premises corrected on inspection)

* **`constraint_geo` is not stale.** `window_start = 2025-12-13` is the *start of the
  240-day trailing fit window*, computed as `score_end − 240d`, **not** a freshness
  stamp. `sf_window_meta`'s newest map-v1 row is
  `window_start=2025-12-13, window_end=2026-08-10, score_start=2026-08-03,
  score_end=2026-08-10` — the served week is [Aug 3, Aug 10), current. The
  `ercot-map-refresh` cron runs and completes weekly (last success 2026-08-09) and
  advances one week per run. Judge freshness by `score_end`, not `window_start`. No
  refresh needed.

## Context

* **The ingest guard already exists.** `ercot_ingest/loaders.py::_f` (~line 705) coerces
  NaN to `None`, every `gen_*` column in `load_wind_hourly` routes through it, and its
  docstring records the original finding — *"8 rows in `wind_hourly_regional` and 6 in
  `solar_hourly_regional` were already storing NaN when this was found."* So this is a
  **data repair of rows written before that fix**, not a new guard. Do not re-add one.
* Why it matters: Postgres stores NaN in `DOUBLE PRECISION` as a **non-null value**, so
  `IS NULL` misses it and any aggregate poisons to NaN. NaN compares false to
  everything, so a sort over a series containing one returns an unsorted list and every
  percentile taken from it is silently wrong — which is what the Context panel reads.
* Affected days are DST spring-forward: 2025-03-09, 2026-03-08, 2026-04-03. The
  prototype drops them at read time; production should not have to.
* `load_by_zone` stalling means the delivery day has no actual, so the Conditions panel
  ranks a forecast against a window of forecasts and says nothing about realized load.
  **Diagnosis (done):** the stop is a live-scheduling gap against a lagging report,
  ruled in by a raw-API probe, not a source retirement or a loader exception.
  * The `ercot-ingest` cron runs every 15 min through today; `[loads]` logs a clean
    `0 fetched, 0 new` each cycle — an exception would log `FAILED` and roll back,
    leaving no `ingest_log` row, so the loader is not throwing.
  * A raw probe of `/np6-345-cd/act_sys_load_by_wzn` (bypassing the loader) shows
    **HTTP 200 with 24 records for every day 2026-07-23 → ~D−2**, same path and same
    fields as 2026-07-22 — the source is healthy; NP6-345-CD publishes a delivery
    day's actuals ~2 days late (on 2026-08-13 the newest available was 2026-08-11).
  * The live loop uses one 2-hour window per cycle, which for a `date`-param endpoint
    collapses to `operatingDay = today` — always empty for a report this lagged — and
    nothing revisits a day once it lands. The earlier 2026-07-24/25 by-name backfill
    returned 0 only because those days had not published *yet*; they serve 24 now.
  * So `loads` only ever stayed current via periodic manual backfills; when those
    stopped after ~2026-07-24 the series froze. The durable fix is a per-day
    lookback (`update_recent_lagged`), self-throttled, exceeding the publish lag.
* `constraint_geo`: **not stale — see the Goal correction.** `window_start` is the
  trailing-window origin (`score_end − 240d`), so 2025-12-13 is what a *fresh* refit
  writes when the served week is [Aug 3, Aug 10). Do not "refresh" it.

## Approach

* Work in: `ercot_ingest/loaders.py`, `ercot_ingest/backfill.py`, `ercot_ingest/tests/`
* **NaN guard (test only — rows already clean).** The scan
  `WHERE gen_x <> gen_x` (the only predicate that finds NaN; `IS NULL` will not) over
  every numeric column of both tables returns 0 on prod, so there is nothing to repair.
  Keep the guard honest with a regression test: feed a frame containing NaN through
  `load_wind_hourly` and assert the persisted value is NULL (the test captures the tuple
  handed to `executemany` and asserts the NaN cell is `None`, which psycopg binds as SQL
  NULL) — pinning `_f`'s behaviour so a future refactor cannot quietly drop it.
* **`load_by_zone` (the real fix).** Done in code:
  1. Tag `ENDPOINTS["loads"]` with `"lagged": True` and add `update_recent_lagged`
     (`backfill.py`): iterate the last `LAGGED_LOOKBACK_DAYS=7` delivery days by name,
     self-throttled via `is_completed` (a 0-row day stays retryable, a landed day
     settles). `live_updater` skips `loads` in the 2-hour loop and calls it after
     `update_recent_daily`. Idempotent via the loader's `ON CONFLICT DO NOTHING`.
     Verified end-to-end against the dev DB (fetched + inserted 2026-08-06 → 08-11).
  2. **One-time prod backfill of the older gap** (2026-07-23 → ~D−2), which predates
     the 7-day lookback: run `backfill.py --endpoint loads --start 2026-07-23 --end
     <today>` in-cluster, then confirm `max(operating_day)` advances. Operational step
     — a prod DB write — left for the operator; not runnable from the dev sandbox.
* Do NOT touch: `_f` itself, `constraint_geo` / the map-refresh cronjob (not stale — see
  Context), the modeling path, or any panel that currently drops NaN rows at read time.

## Acceptance

* [x] `SELECT count(*) FROM wind_hourly_regional WHERE gen_system_wide <> gen_system_wide` returns 0, and the same holds for every `gen_*` column and for `solar_hourly_regional`. **Already true on prod** — no repair needed.
* [x] A regression test asserts NaN input to `load_wind_hourly` persists as SQL NULL. **Done** (`ercot_ingest/tests/test_loaders_nan.py`).
* [~] `load_by_zone` has rows through the current delivery day; the root cause of the 2026-07-22 stop is written down in the PR. **Root cause established (lagging report + no live lookback); durable fix (`update_recent_lagged`) landed and verified on the dev DB. Remaining: one-time prod backfill of 2026-07-23 → D−2 (operator-run) and deploy. "Current" = up to the ~2-day publish lag.**
* [x] ~~`constraint_geo` reports a `window_start` within the last refresh cycle, not 2025-12-13.~~ **Void — premise was a misread.** `window_start` is the 240-day trailing-window origin; the served week (`score_end`) is current. Judge freshness by `score_end`.
* [x] ~~Percentiles over a DST spring-forward day match a hand-checked value.~~ **Moot** — the series is NaN-free on prod, so no read-time distortion remains to hand-check; the regression test pins the guard going forward.
