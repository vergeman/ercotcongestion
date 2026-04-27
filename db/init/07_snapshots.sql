-- Sprint 4 snapshot storage
-- One row per (interval_ts, bus) for per-bus signals.
-- One row per interval_ts for snapshot-wide metadata.

DROP TABLE IF EXISTS bus_snapshots;
DROP TABLE IF EXISTS snapshot_meta;

CREATE TABLE bus_snapshots (
    interval_ts  timestamptz      NOT NULL,
    bus_id       text             NOT NULL,
    fragility    double precision,
    lmp          double precision,
    PRIMARY KEY (interval_ts, bus_id)
);

CREATE INDEX bus_snapshots_ts_idx
    ON bus_snapshots (interval_ts DESC);

CREATE INDEX bus_snapshots_bus_idx
    ON bus_snapshots (bus_id);

CREATE INDEX bus_snapshots_fragility_idx
    ON bus_snapshots (fragility DESC NULLS LAST)
    WHERE fragility IS NOT NULL;


CREATE TABLE snapshot_meta (
    interval_ts            timestamptz PRIMARY KEY,
    status                 text             NOT NULL,
    computed_at            timestamptz      NOT NULL DEFAULT now(),
    -- OPF outputs
    objective_cost         double precision,
    total_load_mw          double precision,
    total_gen_mw           double precision,
    n_binding_lines        integer,
    lmp_min                double precision,
    lmp_mean               double precision,
    lmp_max                double precision,
    fragility_total        double precision,
    fragility_top10_share  double precision,
    -- Diagnostics (variable shape, JSONB)
    binding_lines          jsonb,   -- [{"line": "L3755", "shadow_price": 47.64}, ...]
    top_contingencies      jsonb,   -- [{"line": "L3704", "stress": 1.99}, ...]
    dispatch_by_carrier    jsonb,   -- {"gas": 18896, "solar": 22973, ...}
    wind_factor_by_region  jsonb,   -- {"panhandle": 0.36, "coastal": 0.33, ...}
    solar_factor_by_region jsonb,   -- {"centerwest": 0.80, ...}
    outage_posting_ts      timestamptz,
    -- Failure tracking (status != 'ok')
    error_message          text
);

CREATE INDEX snapshot_meta_status_idx
    ON snapshot_meta (status, interval_ts DESC);
