# 0061 - np4191-dam-shadow-prices-ingest

Type: feat
Branch: feat/0061-np4191-dam-shadow-prices-ingest

## Goal

* Add NP4-191-CD (DAM Binding/Active Constraint Shadow Prices) as a new
  ingest endpoint, following the existing NP6-86-CD (SCED shadow prices)
  pattern end-to-end.
* Land hourly per-constraint rows into a new `ercot_dam_shadow_prices`
  hypertable, keyed `(interval_ts, constraint_id, contingency_name)`.
* Unlock the implied-binding-proximity work (plan 0062), which regresses SP
  congestion on μ from this feed.

## Context

* Pre-existing: NP6-86-CD SCED shadow prices are ingested as `shadow` in
  `ENDPOINTS` and land in `shadow_prices` — the RT/5-min variant.
* NP4-191-CD is the DAM/hourly variant of the same report. Same schema
  intent (constraint + contingency + shadow price + limit/value/violation),
  different report code, hour-ending time grain instead of SCED timestamp.
* NP4-190-CD (already ingested) publishes only total SPP with no three-part
  split; NP4-183-CD publishes bus LMP only. No public feed provides SP-level
  MCL, so we accept losses as a residual in plan 0062 — this ingest work
  does not add a losses dataset.
* Backfill target window matches the other DAM endpoints already in use
  (2025-01-01 onward, per `backfill_ingest_job.yml`).

## Approach

* Work in: `ercot_ingest/`, `db/migrations/`, `ops/deploy/jobs/`,
  `ops/deploy/backfills.sh`.
* Entry point / primary change: new `load_dam_shadow_prices` in
  `loaders.py`, new `dam_shadow` entry in `ENDPOINTS` in `backfill.py`, new
  live-window fetch block in `ErcotClient.py`.

* **Migration** — `db/migrations/20_dam_shadow_prices.sql`:
  * Model after `db/migrations/12_dam_spp.sql` (hypertable) and after the
    existing `shadow_prices` table columns (used by NP6-86).
  * Columns: `interval_ts TIMESTAMPTZ NOT NULL`, `dst_flag BOOLEAN NOT NULL
    DEFAULT FALSE`, `constraint_id INT NOT NULL`, `constraint_name TEXT
    NOT NULL`, `contingency_name TEXT NOT NULL`, `shadow_price DOUBLE
    PRECISION`, `limit_mw DOUBLE PRECISION`, `value_mw DOUBLE PRECISION`,
    `violated_mw DOUBLE PRECISION`, `from_station TEXT`, `to_station TEXT`,
    `from_kv DOUBLE PRECISION`, `to_kv DOUBLE PRECISION`.
  * Primary key: `(interval_ts, constraint_id, contingency_name, dst_flag)`
    — mirrors the (ts, key) uniqueness assumption the regression relies on.
  * `SELECT create_hypertable('ercot_dam_shadow_prices', 'interval_ts',
    if_not_exists => TRUE);`
  * Index on `(interval_ts)` for the panel-pivot query; index on
    `(constraint_name, contingency_name)` for constraint-lookup diagnostics.

* **Loader** — `ercot_ingest/loaders.py`:
  * Add `load_dam_shadow_prices(conn, df)` modeled after
    `load_shadow_prices` (NP6-86) but with hourly time semantics from
    `load_dam_spp` (DAM SPP): parse `deliveryDate` + `hourEnding`
    (`"01:00".."24:00"`) + `DSTFlag`, build `interval_ts` via
    `_to_interval_ts(op_day, hour, 1, dst)`.
  * `ON CONFLICT (interval_ts, constraint_id, contingency_name, dst_flag)
    DO UPDATE` on the numeric fields, so re-ingest overwrites cleanly.
  * Assert-log on ingest that `value_mw == limit_mw` per NP4-191's
    binding-rows-only convention (warn, don't raise) — a future ERCOT
    change to publish non-binding rows would show up here.

* **Backfill / live registry** — `ercot_ingest/backfill.py`:
  * Add `dam_shadow` to `ENDPOINTS`:
    ```
    "dam_shadow": {
        "path": "/np4-191-cd/dam_shadow_prices",
        "loader": load_dam_shadow_prices,
        "from_param": "deliveryDateFrom",
        "to_param": "deliveryDateTo",
        "param_format": "date",
    }
    ```
  * Verify actual path via ERCOT public API catalog before committing —
    stub above follows the family convention but must be confirmed.
  * `live_updater.py`: no code change (loops over `ENDPOINTS`).

* **Live-window fetch** — `ercot_ingest/ErcotClient.py`:
  * Add a `Fetching NP4-191-CD…` block modeled after the existing NP4-190
    block; insert path via `load_dam_shadow_prices(conn, dam_shadow_df)`
    in the ingest section that reports per-endpoint row counts.

* **Backfill job** — `ops/deploy/jobs/backfill_ingest_job.yml`:
  * Update the header comment's endpoint list from "11 endpoints" to "12
    endpoints" and add `dam_shadow` to the enumerated list.
  * No command change (backfill iterates `ENDPOINTS` automatically).

* **Cron job** — `ops/deploy/jobs/ingest_cronjob.yml`:
  * No change. `activeDeadlineSeconds: 600` remains generous — NP4-191 is
    ~50–200 rows per hour × 2 hours per cycle.

* **Backfill script** — `ops/deploy/backfills.sh`:
  * No change. `run_job backfill_ingest_job.yml` already covers the added
    endpoint. Confirm by running with `--endpoint dam_shadow` for the
    initial one-off historical fill.

* **Retire NP6-86-CD (RT/SCED shadow prices)** — table has no downstream
  reader; rip out the ingest path and drop the table:
  * Remove `load_shadow_prices` / `print_top_shadow_prices` from
    `loaders.py`, the `"shadow"` entry from `backfill.py::ENDPOINTS`, and
    the NP6-86 fetch/print block from `ErcotClient.py`.
  * Drop the `shadow_prices` MIN/EXISTS clauses from
    `db/job_queries/backfill_ingest.sql`.
  * `ops/deploy/jobs/backfill_ingest_job.yml`: drop `shadow` from the
    enumerated list (net endpoint count: 11 → 12 with `dam_shadow`).
  * New migration `db/migrations/21_drop_shadow_prices.sql`:
    `DROP TABLE IF EXISTS shadow_prices;`.

* Do NOT touch: other loaders/endpoints; the compute pipeline (that's plan
  0062).

## Acceptance

Code-level (verified in tree):

* [x] `db/migrations/20_dam_shadow_prices.sql` written: hypertable +
  `(interval_ts)` and `(constraint_name, contingency_name)` indexes; PK
  `(interval_ts, constraint_id, contingency_name, dst_flag)`.
* [x] `load_dam_shadow_prices` added to `ercot_ingest/loaders.py` with
  hourly `interval_ts` and `ON CONFLICT ... DO UPDATE` on numeric fields.
  Warn-log (non-raising) when `constraintValue != constraintLimit`.
* [x] `dam_shadow` registered in `ENDPOINTS` in `ercot_ingest/backfill.py`
  and added to `--endpoint` choices.
* [x] Live-window fetch block for NP4-191-CD added to
  `ercot_ingest/ErcotClient.py`.
* [x] NP6-86-CD path retired: `load_shadow_prices`,
  `print_top_shadow_prices`, `"shadow"` endpoint, and the live fetch/print
  block removed. `db/job_queries/backfill_ingest.sql` cleaned. Backfill
  job manifest header updated (11 endpoints net after add + drop).
* [x] `db/migrations/21_drop_shadow_prices.sql` written
  (`DROP TABLE IF EXISTS shadow_prices;`).
* [x] No remaining references to `shadow_prices` / NP6-86 in
  `ercot_ingest/`, `db/job_queries/`, or `ops/deploy/` (grep-verified).
