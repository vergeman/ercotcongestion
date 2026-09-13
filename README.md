# [ERCOT Congestion Explorer](https://ercotcongestion.com)

ERCOT Congestion Explorer maps where congestion is priced across ERCOT and
recovers the estimated shift factors behind it. Use the map to query hourly
day-ahead prices, while visualizing the electrical footprints of the binding
constraints that drive them. A forecast for the next delivery day is generated
and evaluated.

<video src="https://ercotcongestion.com/screenshots/ercot-congestion-intro.mp4" controls muted playsinline width="100%">
  ERCOT Congestion Explorer walkthrough
</video>

## The Four Pages

- [**Brief**](https://ercotcongestion.com/): a daily scan of nodal congestion
  and constraint shadow prices that stand out from their recent range.
- [**Map**](https://ercotcongestion.com/map): nodal congestion, LMPs, and each
  constraint's electrical footprint. Switch between forecast and settled data;
  use hourly playback to see when and where congestion occurs.
- [**Matrix**](https://ercotcongestion.com/matrix): explores recovered shift
  factors and each constraint's contribution to a settlement point—the "why"
  behind a node's price.
- [**Scoreboard**](https://ercotcongestion.com/scoreboard): evaluates the
  forecast over time and against baselines.

## Method

The explorer collects ERCOT's published binding-constraint shadow prices, nodal
prices, system price, and forecast inputs. A weekly job estimates a shift factor
matrix that describes a constraint's effect on settlement points; daily forecast
jobs predict the next constraints' shadow-price signal and project it through
that map.

At each settlement point, congestion is estimated as the sum of the active
constraints' shadow prices (`μ`) weighted by their recovered shift factors
(`SF`): `congestion = −Σ SF · μ`. This is what maps a constraint's footprint and
lets the shift factor matrix trace a node's price to the constraints that
contribute to it.

## Quickstart

### Prerequisites

- Docker Engine, Docker Compose v2
- ERCOT API credentials for a working ingest cron job (`ERCOT_USERNAME`,
  `ERCOT_PASSWORD`, and `ERCOT_SUBSCRIPTION_KEY`)

### Run locally

1. Create local configuration from the checked-in template and supply the
   values it requires. For a standard local database, set `PG_USER=ercot`,
   `PG_PASSWORD` to a local-only password, `PG_HOST=db`, `PG_PORT=5432`, and
   `PG_DATABASE=ercot`.

   ```sh
   cp .env.stub .env.dev
   $EDITOR .env.dev
   ```

2. Start the development stack.

   ```sh
   docker compose up --build
   ```

   The API is available at <http://localhost:8000> and the Vite web app at
   <http://localhost:5173>. The `updater` service continuously refreshes ERCOT
   inputs in local development. Due to rate limiting, data will take time to
   collect.

### Database migrations

On a fresh clone, `docker compose up` initializes the empty Postgres volume and
runs every SQL file in `db/migrations/` automatically. When adding a migration
to an already-initialized local database, apply that file explicitly:

```sh
docker compose exec -T db psql -U ercot -d ercot < db/migrations/NN_description.sql
```

Use the actual configured database user and name if they differ from the local
defaults. See [`db/README.md`](db/README.md) for database and backup guidance.

## Operating architecture

* **API (`api/`):** a FastAPI service over Postgres. It exposes topology,
  settled conditions, map, matrix, forecast, scoreboard, and brief endpoints.
* **Web (`web/`):** a React/Vite single-page app. It fetches from the API;
  it does not embed the analytical data or compute the model in the browser.

Postgres/TimescaleDB is the data store for the project; hosting ERCOT ingestion,
model cron jobs, and the API. The `compute/` package contains the model and
scheduled-job entry points; `ercot_ingest/` obtains ERCOT public data and writes
it to the database.

### Scheduled production jobs

Several Kubernetes CronJobs in [`ops/deploy/jobs`](ops/deploy/jobs):

| Job                      | Cadence           | Responsibility                                                                               |
|--------------------------|-------------------|----------------------------------------------------------------------------------------------|
| `ercot-ingest`           | Every 15 minutes  | Runs `ercot_ingest/live_updater.py --once` to ingest current ERCOT inputs.                   |
| `ercot-forecast`         | Daily, 17:00 UTC  | Fits and publishes the T+1 final nodal congestion forecast.                                  |
| `ercot-forecast-preview` | Daily, 20:15 UTC  | Publishes the T+2 preview forecast, preserved separately from the final.                     |
| `ercot-map-refresh`      | Sunday, 18:00 UTC | Refreshes the rolling shift-factor map, its geographic footprints, and evaluation artifacts. |

The weekly map (`ercot-map-refresh`) calculates the shift factor relationship
between constraint shadow prices and settlement-point congestion. The daily
forecast supplies the time-varying constraint signal; together they produce the
nodal forecast. The detailed operating runbook is in
[`compute/README.md`](compute/README.md).

## Repository guide

Each directory has its own README or local documentation with more detail.

```text
api/            FastAPI routes, schemas, service layer, and API tests
compute/        Shift-factor map, congestion forecast, evaluations, and job CLIs
db/             SQL migrations, database utilities, and backup/restore tooling
ercot_ingest/   ERCOT API clients, loaders, refresh loop, and backfill tools
preprocess/     EIA, zonal, and geographic-data preparation
shared/         Configuration and Python code shared across services
web/            React/Vite frontend explorer, static assets
ops/            Kubernetes (K3s) manifests, deployment scripts, and scheduled-job definitions
docs/           Product and technical documentation
plan/           Design notes and implementation plans
data/           Local input and derived data assets (not the application source)
```

## Scope and limitations

The explorer estimates shift factors from public market data; it is not an
official ERCOT network model, and nowhere near authoritative.

## License

See [LICENSE](LICENSE). You may use, copy, modify, and share this project for
any purpose; it is provided as-is.
