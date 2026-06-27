# 0008 - Timestamp Data Migration

Type: fix
Branch: fix/0008-timestamp-data-migration

## Goal

* Loaders that store ERCOT API timestamps verbatim must localize CT → UTC
  before insert.
* Backfill existing rows in affected tables to correct the 5h/6h offset.
* New ingest cycles produce timestamps that match real-world UTC within a
  few minutes of `now()`.

## Context

* ERCOT returns `SCEDTimestamp` / `postedDatetime` as naive strings in
  Central Time. psycopg inserts them into TIMESTAMPTZ at the session TZ
  (UTC), so CT values get mislabeled as UTC — a 5h (CDT) / 6h (CST) shift.
* Discovered during 0007. Pre-existing in `shadow_prices` and
  `outages_zonal`; inherited by the new `sced_system_lambda`,
  `ercot_rt_lmp`, and `load_forecast_zonal` loaders.
* `_to_interval_ts()`-based loaders are unaffected — they already do the
  CT→UTC conversion.

## Approach

* Work in: `ercot_ingest/loaders.py`
* Entry point / primary change: every loader that reads `SCEDTimestamp` or
  `postedDatetime` directly from the dataframe.
* Step 1 — add a small helper (e.g. `_ercot_ts_to_utc(s)`) that parses the
  naive string, attaches `America/Chicago` (with `fold` if a
  `repeatedHourFlag`/`DSTFlag` is present), and converts to UTC.
* Step 2 — apply it in `load_shadow_prices`, `load_outages`,
  `load_sced_lambda`, `load_rt_lmp`, `load_load_forecast`.
* Step 3 — one-off SQL migration to shift existing rows. Two windows:
  CST (`+6h`) for rows before the spring DST cutover, CDT (`+5h`) after.
  Use `AT TIME ZONE 'America/Chicago' AT TIME ZONE 'UTC'` to let Postgres
  resolve DST per-row instead of hardcoding offsets.
* Do NOT touch: loaders that already use `_to_interval_ts()` (load,
  wind, solar, zonal_lmp, dam_*); their stored UTC is correct.
