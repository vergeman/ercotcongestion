
-- NP6-345-CD: Actual System Load by Weather Zone (15-min)
CREATE TABLE IF NOT EXISTS load_by_zone (
    operating_day  DATE             NOT NULL,
    hour_ending    SMALLINT         NOT NULL,
    interval_id    SMALLINT         NOT NULL,  -- 1-4 for 15-min intervals
    coast          DOUBLE PRECISION,
    east           DOUBLE PRECISION,
    far_west       DOUBLE PRECISION,
    north          DOUBLE PRECISION,
    north_central  DOUBLE PRECISION,
    south_central  DOUBLE PRECISION,
    southern       DOUBLE PRECISION,
    west           DOUBLE PRECISION,
    total          DOUBLE PRECISION,
    dst_flag       BOOLEAN,
    interval_ts    TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (interval_ts, dst_flag)
);
SELECT create_hypertable('load_by_zone', 'interval_ts', if_not_exists => TRUE);
