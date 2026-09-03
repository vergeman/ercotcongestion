# Compute

Production forecasts are database-backed. `daily_forecast` publishes one
delivery day, `backfill_forecasts` replays that path over a date range, and
`backfill_scoreboard` performs its historical walk-forward evaluation and writes
weekly rows directly to `scoreboard_weekly`.

`weekly_map` persists the causal shift-factor windows used by daily and
historical forecast publication.

Run tests with the compute service:

```
docker compose run --rm --no-deps compute python -m pytest /compute -q
```

Historical forecast publication:

```
python -m compute.jobs.backfill_forecasts --run-id mu-all-v1 --map-run-id map-v1 \
  --start 2025-01-08 --end 2025-12-31 --to-db
```

Historical scoreboard publication:

```
python -m compute.jobs.backfill_scoreboard --run-id mu-all-v1 \
  --start 2025-01-01 --end 2025-12-31
```

`MU_SPILL_DIR` may select a disk location for bounded-memory backfills. Each job
creates and removes its own temporary workspace there.
