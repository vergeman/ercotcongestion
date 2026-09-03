# Forecast persistence

Forecast products are durable Postgres rows, not run-directory files.

`forecast_nodal` holds point forecasts keyed by `run_id`, delivery day, horizon,
timestamp, and settlement point. `forecast_sf_artifact` holds the corresponding
shift-factor and expected-μ payload keyed by `run_id`, delivery day, and horizon.
`forecast_current` selects the served run.

`scoreboard_weekly` retains walk-forward evaluation results keyed by `run_id`,
week, and source. Run IDs are durable model provenance.

Historical jobs can create panel spills, bind matrices, prediction chunks, and
combined predictions beneath `MU_SPILL_DIR` (or the system temporary directory).
They are job-owned scratch data and are removed on success and failure.
