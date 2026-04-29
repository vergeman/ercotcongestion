DROP TABLE IF EXISTS wind_hourly;
DROP TABLE IF EXISTS solar_hourly;

-- Wind: 5 regions (Panhandle, Coastal, South, West, North)
CREATE TABLE IF NOT EXISTS wind_hourly_regional (
    delivery_date    date NOT NULL,
    hour_ending      smallint NOT NULL,
    posted_datetime  timestamptz NOT NULL,
    interval_ts      timestamptz NOT NULL,
    dst_flag         boolean NOT NULL,
    -- System-wide (kept for sanity checks vs. regional sum)
    gen_system_wide       double precision,
    cop_hsl_system_wide   double precision,
    stwpf_system_wide     double precision,
    wgrpp_system_wide     double precision,
    hsl_system_wide       double precision,
    -- Per region
    gen_panhandle         double precision,
    cop_hsl_panhandle     double precision,
    stwpf_panhandle       double precision,
    wgrpp_panhandle       double precision,
    gen_coastal           double precision,
    cop_hsl_coastal       double precision,
    stwpf_coastal         double precision,
    wgrpp_coastal         double precision,
    gen_south             double precision,
    cop_hsl_south         double precision,
    stwpf_south           double precision,
    wgrpp_south           double precision,
    gen_west              double precision,
    cop_hsl_west          double precision,
    stwpf_west            double precision,
    wgrpp_west            double precision,
    gen_north             double precision,
    cop_hsl_north         double precision,
    stwpf_north           double precision,
    wgrpp_north           double precision,
    PRIMARY KEY (interval_ts, dst_flag)
);

CREATE INDEX wind_hourly_regional_interval_ts_idx
  ON wind_hourly_regional (interval_ts DESC);

-- Solar: 6 regions (CenterWest, NorthWest, FarWest, FarEast, SouthEast, CenterEast)
CREATE TABLE IF NOT EXISTS solar_hourly_regional (
    delivery_date    date NOT NULL,
    hour_ending      smallint NOT NULL,
    posted_datetime  timestamptz NOT NULL,
    dst_flag         boolean NOT NULL,
    interval_ts      timestamptz NOT NULL,
    gen_system_wide       double precision,
    cop_hsl_system_wide   double precision,
    stppf_system_wide     double precision,
    pvgrpp_system_wide    double precision,
    hsl_system_wide       double precision,
    gen_centerwest        double precision,
    cop_hsl_centerwest    double precision,
    stppf_centerwest      double precision,
    pvgrpp_centerwest     double precision,
    gen_northwest         double precision,
    cop_hsl_northwest     double precision,
    stppf_northwest       double precision,
    pvgrpp_northwest      double precision,
    gen_farwest           double precision,
    cop_hsl_farwest       double precision,
    stppf_farwest         double precision,
    pvgrpp_farwest        double precision,
    gen_fareast           double precision,
    cop_hsl_fareast       double precision,
    stppf_fareast         double precision,
    pvgrpp_fareast        double precision,
    gen_southeast         double precision,
    cop_hsl_southeast     double precision,
    stppf_southeast       double precision,
    pvgrpp_southeast      double precision,
    gen_centereast        double precision,
    cop_hsl_centereast    double precision,
    stppf_centereast      double precision,
    pvgrpp_centereast     double precision,
    PRIMARY KEY (interval_ts, dst_flag)
);

CREATE INDEX solar_hourly_regional_interval_ts_idx
  ON solar_hourly_regional (interval_ts DESC);
