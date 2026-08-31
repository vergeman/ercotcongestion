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
| `backfill_artifacts.py` | Replays the daily forecast path across a date range to produce production-equivalent nodal forecasts and SF+μ artifacts. Resumable and intentionally resource-intensive. | Manual |
| `backfill_forecast_history.py` | Builds queryable per-constraint daily forecast history from existing SF+μ artifacts, without refitting forecasts. | Manual |
| `backfill_nodal.py` | Projects an offline walk-forward μ prediction artifact through the SF map to seed historical nodal forecasts and verdict data. | Manual |
| `backfill_brief_grade_prod.sh` | Runs `materialize_brief_grade` in resumable 30-day production batches, starting from the latest settled day. | Manual, production compute shell |
| `backfill_scoreboard.py` | One-shot/reload importer that writes an offline backtest run’s precomputed weekly μ scores to `scoreboard_weekly`; it does not recompute metrics. | Manual, after offline scoring |

## Review and package support — on demand

| File | Description | Caller |
| --- | --- | --- |
| `render_hero_golden.py` | Renders a checked-in 365-day text audit of hero copy for manual vocabulary review; it is not a serving or persistence path. | Manual |
| `__init__.py` | Declares the jobs package and documents the runner layer’s boundary from import-only forecasting and map libraries. | Python imports |
