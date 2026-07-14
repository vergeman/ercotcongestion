-- 26_dam_close_forecasts.sql
--
-- Vintaged wind/solar forecasts (plan/0085 commit 2).
--
-- WHY THESE TABLES EXIST. `wind_hourly_regional` / `solar_hourly_regional`
-- (migration 06) are keyed `(interval_ts, dst_flag)` — ONE row per hour, and the
-- loader deduplicates to the *most recent posting*. That is correct for "what
-- actually happened" and useless for forecasting: the surviving row is the
-- version ERCOT published ~49h AFTER the hour it describes (measured median
-- lag +48.9h), so it carries realized `gen_*` and a post-hoc forecast. Measured:
-- **0.0%** of stored rows were published early enough to have been knowable at
-- DAM close. Training on them would fabricate skill — the exact failure mode
-- plan/0085 names ("the single easiest way to fabricate skill here is a
-- lookahead feature, and this project has already caught itself once").
--
-- These tables are keyed on `(posted_datetime, interval_ts, dst_flag)`, so a
-- publication is a fact with a timestamp rather than a row to be overwritten.
-- A feature may then read only vintages with `posted_datetime <= prediction_ts`.
--
-- Migration 06's tables are untouched and remain the source of ACTUALS.
--
-- THE BUILT-IN LEAK ALARM: in a vintage posted before DAM close, the delivery-day
-- rows have `gen_* IS NULL` (the hour has not happened). A non-null `gen_*` on a
-- row whose `interval_ts > posted_datetime` would mean ERCOT published an actual
-- for a future hour — impossible, so it would mean our ingest mixed vintages.
-- The CHECK constraint below makes that unrepresentable rather than merely
-- untested.

CREATE TABLE IF NOT EXISTS wind_forecast_regional (
    posted_datetime  TIMESTAMPTZ NOT NULL,
    interval_ts      TIMESTAMPTZ NOT NULL,
    delivery_date    DATE        NOT NULL,
    hour_ending      SMALLINT    NOT NULL,
    dst_flag         BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Realized generation. NULL for any hour not yet elapsed at posted_datetime;
    -- that is the invariant the CHECK enforces.
    gen_system_wide       DOUBLE PRECISION,
    gen_panhandle         DOUBLE PRECISION,
    gen_coastal           DOUBLE PRECISION,
    gen_south             DOUBLE PRECISION,
    gen_west              DOUBLE PRECISION,
    gen_north             DOUBLE PRECISION,

    -- STWPF: Short-Term Wind Power Forecast (ERCOT's point forecast).
    stwpf_system_wide     DOUBLE PRECISION,
    stwpf_panhandle       DOUBLE PRECISION,
    stwpf_coastal         DOUBLE PRECISION,
    stwpf_south           DOUBLE PRECISION,
    stwpf_west            DOUBLE PRECISION,
    stwpf_north           DOUBLE PRECISION,

    -- WGRPP: the ~80th-percentile "reasonably probable" forecast. Kept because
    -- (stwpf, wgrpp) together carry ERCOT's own uncertainty band — a natural
    -- covariate for a model whose output is a P10/P50/P90.
    wgrpp_system_wide     DOUBLE PRECISION,
    wgrpp_panhandle       DOUBLE PRECISION,
    wgrpp_coastal         DOUBLE PRECISION,
    wgrpp_south           DOUBLE PRECISION,
    wgrpp_west            DOUBLE PRECISION,
    wgrpp_north           DOUBLE PRECISION,

    cop_hsl_system_wide   DOUBLE PRECISION,

    PRIMARY KEY (posted_datetime, interval_ts, dst_flag),
    CONSTRAINT wind_forecast_no_future_actual
        CHECK (gen_system_wide IS NULL OR interval_ts <= posted_datetime)
);

SELECT create_hypertable('wind_forecast_regional', 'interval_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_wind_forecast_posted
  ON wind_forecast_regional (posted_datetime DESC, interval_ts);


CREATE TABLE IF NOT EXISTS solar_forecast_regional (
    posted_datetime  TIMESTAMPTZ NOT NULL,
    interval_ts      TIMESTAMPTZ NOT NULL,
    delivery_date    DATE        NOT NULL,
    hour_ending      SMALLINT    NOT NULL,
    dst_flag         BOOLEAN     NOT NULL DEFAULT FALSE,

    gen_system_wide       DOUBLE PRECISION,
    gen_centerwest        DOUBLE PRECISION,
    gen_northwest         DOUBLE PRECISION,
    gen_farwest           DOUBLE PRECISION,
    gen_fareast           DOUBLE PRECISION,
    gen_southeast         DOUBLE PRECISION,
    gen_centereast        DOUBLE PRECISION,

    -- STPPF: Short-Term PV Power Forecast. PVGRPP: the probable-band analogue.
    stppf_system_wide     DOUBLE PRECISION,
    stppf_centerwest      DOUBLE PRECISION,
    stppf_northwest       DOUBLE PRECISION,
    stppf_farwest         DOUBLE PRECISION,
    stppf_fareast         DOUBLE PRECISION,
    stppf_southeast       DOUBLE PRECISION,
    stppf_centereast      DOUBLE PRECISION,

    pvgrpp_system_wide    DOUBLE PRECISION,
    pvgrpp_centerwest     DOUBLE PRECISION,
    pvgrpp_northwest      DOUBLE PRECISION,
    pvgrpp_farwest        DOUBLE PRECISION,
    pvgrpp_fareast        DOUBLE PRECISION,
    pvgrpp_southeast      DOUBLE PRECISION,
    pvgrpp_centereast     DOUBLE PRECISION,

    cop_hsl_system_wide   DOUBLE PRECISION,

    PRIMARY KEY (posted_datetime, interval_ts, dst_flag),
    CONSTRAINT solar_forecast_no_future_actual
        CHECK (gen_system_wide IS NULL OR interval_ts <= posted_datetime)
);

SELECT create_hypertable('solar_forecast_regional', 'interval_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_solar_forecast_posted
  ON solar_forecast_regional (posted_datetime DESC, interval_ts);
