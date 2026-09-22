# Compute jobs

Command-line runners and their database-write orchestration live here.  Recurring
production work is scheduled by the manifests in `ops/deploy/jobs/`; backfills and
review tools are run manually.

## Forecast publication — daily

| File | Description | Caller |
| --- | --- | --- |
| `daily_forecast.py` | Fits and publishes the daily nodal forecast and SF+μ artifact for one delivery day. Runs daily for both final (T+1) and preview (T+2) tracks. | `forecast_cronjob.yml` and `forecast_preview_cronjob.yml` |
| `forecast_history.py` | Helper module, not a standalone job: decodes an SF+μ artifact and upserts per-constraint daily forecast totals. | `daily_forecast.py` |

## Forecast grading — daily / after settlement

| File | Description | Caller |
| --- | --- | --- |
| `grade_forecast_day.py` | Grades the served nodal forecast against settled DAM results and writes the daily Scoreboard metrics; it does not calculate Brief grades. Normally invoked by `daily_forecast.py`; also supports retrying a missed grade. | `daily_forecast.py`; manual retry |
| `materialize_brief_grade.py` | Writes the Brief’s separate settled detection, magnitude, and timing grades. Normally invoked after the Scoreboard grade and can materialize a requested date range. | `daily_forecast.py`; manual backfill |

## Shift-factor map — weekly

| File | Description | Caller |
| --- | --- | --- |
| `weekly_map.py` | Fits and persists rolling implied shift-factor windows plus diagnostics. The map-refresh CronJob runs it weekly. | `map_refresh_cronjob.yml` |

## Historical backfills — one-time or as needed

| File | Description | Caller |
| --- | --- | --- |
| `backfill_forecasts.py` | Replays the daily forecast path across a date range to publish production-equivalent nodal forecasts and SF+μ artifacts. Resumable and intentionally resource-intensive. | Manual |
| `backfill_forecast_history.py` | Builds queryable per-constraint daily forecast history from existing SF+μ artifacts, without refitting forecasts. | Manual |
| `backfill_brief_grade_prod.sh` | Runs `materialize_brief_grade` in resumable 30-day production batches, starting from the latest settled day. | Manual, production compute shell |
| `backfill_scoreboard.py` | Runs the historical μ walk and evaluation, then writes weekly scores to `scoreboard_weekly`. | Manual |
| `backfill_scoreboard_daily.py` | Regrades existing served forecasts through their stored SF artifacts; dry-run by default and replaces one daily key atomically with `--to-db`. | Manual |

### Daily Scoreboard SF repair

Run each horizon explicitly; this never rewrites forecasts or artifacts:

```sh
python -m compute.jobs.backfill_scoreboard_daily --run-id <id> --horizon 1 --start YYYY-MM-DD --end YYYY-MM-DD --to-db
python -m compute.jobs.backfill_scoreboard_daily --run-id <id> --horizon 2 --start YYYY-MM-DD --end YYYY-MM-DD --to-db
```

Before writing, omit `--to-db` for a dry run. Reconcile each horizon afterward:

```sql
SELECT d.horizon, count(*) AS score_rows, count(a.*) AS artifact_rows
FROM scoreboard_daily d
LEFT JOIN forecast_sf_artifact a USING (run_id, delivery_date, horizon)
WHERE d.run_id = '<id>' AND d.delivery_date BETWEEN '<start>' AND '<end>'
GROUP BY d.horizon;

SELECT f.delivery_date, f.horizon
FROM forecast_nodal f
LEFT JOIN forecast_sf_artifact a USING (run_id, delivery_date, horizon)
WHERE f.run_id = '<id>' AND f.delivery_date BETWEEN '<start>' AND '<end>'
  AND a.run_id IS NULL
GROUP BY f.delivery_date, f.horizon;
```

## Review and package support — on demand

| File | Description | Caller |
| --- | --- | --- |
| `render_hero_golden.py` | Renders a checked-in 365-day text audit of hero copy for manual vocabulary review; it is not a serving or persistence path. | Manual |
| `__init__.py` | Declares the jobs package and documents the runner layer’s boundary from import-only forecasting and map libraries. | Python imports |
