CREATE TABLE IF NOT EXISTS ingest_log (
    endpoint     TEXT        NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end   TIMESTAMPTZ NOT NULL,
    rows_fetched INTEGER     NOT NULL,
    rows_inserted INTEGER    NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (endpoint, window_start, window_end)
);
