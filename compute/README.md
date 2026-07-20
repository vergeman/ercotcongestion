# Compute

## Tests

Run under the `compute` service (mounts the tree, sets `PYTHONPATH`); `--no-deps`
skips the DB container since the suites don't need it:

```
# full compute suite
docker compose run --rm --no-deps compute python -m pytest /compute -q

# just the SF + μ suites
docker compose run --rm --no-deps compute python -m pytest /compute/sf/tests /compute/mu/tests -q

# a single file / test
docker compose run --rm --no-deps compute python -m pytest /compute/mu/tests/test_forecast_day.py -q
```

## Runbook — build & deploy the μ forecast

Two pipelines run over the shared ERCOT DAM ingest (`ercot_dam_shadow_prices`,
`ercot_dam_spp`, `dam_system_lambda`, forecast vintages), coupled in one direction: the
forecast projects its μ prediction through the map's persisted shift factors, so **the
map must be built and fresh before the forecast runs** — a missing or stale map fails the
forecast loud and leaves the prior served day intact.

| | SF map (`map-v1`) | Forecast (`mu-all-v1`) |
|---|---|---|
| What it is | the spatial geography: constraint shadow price → per-SP congestion | the μ product: per-SP P10/P50/P90 congestion forecast |
| Cadence | weekly, Sun 18:00 UTC | daily, 17:00 UTC |
| Cron | `ops/deploy/jobs/map_refresh_cronjob.yml` | `ops/deploy/jobs/forecast_cronjob.yml` |
| Entry | `weekly_map` → `geo_persist` → `eval` | `daily_forecast` |
| Writes | `implied_shift_factors`, `sf_window_meta`, `constraint_geo` | `forecast_nodal`, `forecast_sf_artifact`, pointer `forecast_current[ercot]` |

**μ vs SF — why they are separate.** The two are orthogonal and multiply. μ is the
*temporal* signal: per constraint, per hour, does it bind and how hard — driven by load,
weather, and outages, so it is refit **daily**. SF is the *spatial* map: constraint
shadow price → nodal congestion — grid geography that moves slowly, so it is fit
**weekly** on a 240-day window. Nodal congestion = SF · μ. The map is the sole SF fitter;
the forecast reuses its SF rather than refitting, so one weekly fit serves every daily
forecast.

## Prediction data — the 240-day window

Both stages fit on a **trailing 240-day window**, single-sourced as `WINDOW_DAYS`
in `compute/sf/config.py` (the SF map) and `DEFAULT_TRAIN_DAYS` in
`compute/mu/mu_model.py` (μ). **Every feed obeys that same window** — the DAM
inputs (`ercot_dam_shadow_prices`, `ercot_dam_spp`, `dam_system_lambda`) and the
forecast vintages the μ weather feature correlates against (zonal load, regional
wind/solar) are all read over the same `[D − 240d, D)` span. No feed has a
separate, longer lookback.

The consequence: **a prediction for delivery day `D` needs every feed populated
back to `D − 240d`.** To serve predictions from **2025-01-01**, the ingest must
reach **2024-05-06** (= 2025-01-01 − 240 days). The first 240 days are consumed as
warm-up and are never themselves scored — scoring begins where the first full
window closes.

Build and deploy in this order.

### Step 0 — Preflight

Apply the DB migrations (including `forecast_nodal`, `forecast_current`, and
`forecast_sf_artifact`) and ensure the shared DAM ingest is populated through the
historical end date selected below. The live daily job additionally needs D−1 DAM data
and D's forecast vintages available after DAM close. Run the following compute commands
in an environment with the production DB credentials.

### Dates in the runbook — what each flag controls

The stages take dates literally (they never read `now()` or the DB max), and
`--start` means a **different thing** in each — worth reading before running:

* **SF map `--start`** (`weekly_map`, `eval`) — the *series origin*: the first day
  you want SF windows scored for, **not** the data floor. The loader extends the
  read back a full window on its own (`read_start = start − window_days`), so
  `--start 2025-01-01` reads from 2024-05-06 and scores from 2025-01-01. Leave it
  at the product origin.
* **μ `--start`** (`mu_model`) — the *first day of data read* (the panel floor).
  The walk warms up 240 days from here, so with no `--score-from` the first scored
  week is `--start + 240d`. Set it to the ingest floor, **2024-05-06**.
* **`--score-from`** (`mu_model`) — pins the first scored week explicitly (and the
  walk's phase onto the SF grid) instead of deriving it from `--start`. Set it to
  the product origin, **2025-01-01**.
* **`--end`** — a *fixed* completed date, deliberately not "today," so a rebuild is
  reproducible. Use a recent settled date. The map's `--end <tomorrow>` is the one
  exception: it is incremental and exclusive-ended, so it just reads through the
  latest DAM and advances one week per cron run.

### Step 1 — SF map (build the geography first)

**Needs:** the DAM ingest populated.
**Does:** fits SF for each refit-week boundary on a trailing 240-day window (7-day
cadence), then persists the shift factors, constraint centroids (`geo_persist`), and
stability metrics (`eval`). Runs incrementally: it fits and writes only the complete
refit windows not already present, so a later `--end` appends just the new week(s) and a
repeated `--end` is a no-op. Only complete windows persist (the partial terminal week is
skipped), so the served map is the newest complete week.

```
python -m compute.jobs.weekly_map --run-id map-v1 --start 2025-01-01 --end <tomorrow> \
    --window-days 240 --refit-days 7 --ridge-lambda 1.0 --min-binding-hours 25 --persist-sf

python -m compute.sf.geo_persist --run-id map-v1

python -m compute.sf.eval --run-id map-v1 --start 2025-01-01 --end <tomorrow> \
    --window-days 240 --refit-days 7 --ridge-lambda 1.0 --min-binding-hours 25 --persist-eval
```

* `compute.jobs.weekly_map`: `--start` is the series origin. Add `--rebuild` to
wipe the run and refit from scratch (~30 min / ~67M rows); omit it for the
normal cheap append. **Extending the ingest floor backward** — the initial
2024-05-06 build that fills the 2025-01-01 → 2025-08 windows — is a from-scratch
case: pass `--rebuild`, since a plain append only fits *forward* boundaries it
does not already have.

Hand-run the deployed cronjob on the identical path:
```
cd ops/deploy && source ../../.env && export IMAGE_TAG="$(cat ../../.image-tag)"
kubectl -n ercotstress create job --from=cronjob/ercot-map-refresh map-refresh-manual
```

### Step 2 — Build the μ residual pool

**Does:** walks μ forward over history and writes out-of-sample `(p_bind, mu_gbm)`
predictions. This is both the input to the historical nodal backfill and the residual
pool used to draw P10/P90 bands in the daily job. It is a prod-side operation (~16 GiB).

Use `mu-all-v1` for every forecast artifact and DB write. The SF map deliberately has
its own run ID, `map-v1`.

```
RUN_ID=mu-all-v1
MAP_RUN_ID=map-v1
ART_DIR=/compute/runs/${RUN_ID}/mu
mkdir -p "${ART_DIR}"

# --start is the ingest floor, --score-from the product origin (2025-01-01), and
# --end a fixed recent completed date — see "Dates in the runbook".
python -m compute.mu.mu_model \
    --start 2024-05-06 --score-from 2025-01-01 \
    --preds-out "${ART_DIR}/mu_preds.npz" --end <YYYY-MM-DD>

# The daily job reads this fixed, image-baked path. Copy before the image build.
cp "${ART_DIR}/mu_preds.npz" /compute/mu/mu_preds.npz
```

**`mu_preds.npz` is a live dependency**, not merely a seed artifact: the daily job
loads it every run as the out-of-sample residual pool that draws the P10/P90 bands.
It ships **baked into the image** (`Dockerfile: COPY compute/`; no volume), so rebuild
and redeploy the image after refreshing it.

> **FOOTGUN — `--end` is a fixed default (`2026-07-01`), not "today."** `mu_model` and
> `backfill_nodal` never read the DB max or `now()`. With `--score-from` set (above),
> the scored walk begins there; without it, the walk begins at `--start + 240d` (the
> training warm-up), so the first residual week is about eight months after `--start`.

### Step 3 — Historical nodal-price backfill

**Needs:** step 1's persisted `map-v1` and step 2's predictions.
**Does:** projects every eligible walk-forward prediction through its causal persisted
SF window, writes the P10/P50/P90/point panel for `mu-all-v1`, then promotes that same
run only after the bulk write succeeds. This is the historical price backfill.

```
python -m compute.jobs.backfill_nodal \
    --run-id "${RUN_ID}" --map-run-id "${MAP_RUN_ID}" \
    --preds "${ART_DIR}/mu_preds.npz" \
    --nodal-out "${ART_DIR}/mu_nodal.npz" \
    --out "${ART_DIR}/mu_bands_weekly.csv" --to-db

python -m compute.jobs.backfill_nodal \
    --run-id mu-all-v1 \
    --map-run-id map-v1 \
    --preds /compute/runs/map-v1/mu/mu_preds.npz \
    --nodal-out /compute/runs/map-v1/mu/mu_nodal.npz \
    --out /compute/runs/map-v1/mu/mu_bands_weekly.csv \
    --to-db
```

`mu_nodal.npz` is the audit/reload artifact for the seed. Do not run
`--load-nodal-npz` after the command above: it only reloads that same panel. Use it
only to restore an existing NPZ into a fresh DB:

```
python -m compute.jobs.backfill_nodal \
    --load-nodal-npz "${ART_DIR}/mu_nodal.npz" --run-id "${RUN_ID}"
```

This fast historical path writes `forecast_nodal`, but does not write
`forecast_sf_artifact`: it does not invoke `daily_forecast` once per day.

### Step 4 — Optional production-equivalent historical artifact backfill

If historical driver/what-if support is required as well as historical prices, invoke
the daily job once per eligible UTC delivery date. Each run refits the daily μ model,
replaces that date's nodal rows, and writes its `forecast_sf_artifact`. This is much
more expensive than step 3 and is intentionally not the default history seed.

```
python -m compute.jobs.daily_forecast --delivery-date <YYYY-MM-DD> \
    --run-id "${RUN_ID}" --map-run-id "${MAP_RUN_ID}" \
    --to-db
```

Run it only for dates with complete DAM-close inputs and a causal map window; it fails
loud otherwise. Do not mix a different run ID into this loop. Add `--npz-dir` only
when it names a persistent mounted directory; it is not required for the DB artifacts.

### Step 5 — Daily forecast (append each new day)

**Needs:** a fresh map (step 1) and `mu_preds.npz` in the image (step 2).
**Does:** builds the panel at DAM-close vintage, refits the μ heads on the trailing
window and predicts D's 24 h, loads the map's latest causal SF window, projects μ through
it and draws the bands, writes `forecast_nodal` + `forecast_sf_artifact`, then flips
`forecast_current[ercot]` **last**. The SF loader is guarded: it takes the latest window
with `window_end ≤ D` and fails loud (prior pointer intact) if that window is missing,
stale (`D − window_end > 14d`), or covers `< 50%` of D's predicted binding mass — it
never serves stale geography. Peak ~16 GiB (the pod limit).

```
python -m compute.jobs.daily_forecast --delivery-date tomorrow --run-id mu-all-v1 \
    --map-run-id map-v1 --to-db
```

Gap-fill a single historic day — identical path, only the date changes (drop `--to-db`
for a dry run):
```
kubectl -n ercotstress run forecast-backfill-<DATE> --rm -it --restart=Never \
  --image="${IMAGE_REPO}/ercotstress/api-compute:${IMAGE_TAG}" \
  --overrides='{"spec":{"imagePullSecrets":[{"name":"regcred"}]}}' \
  --env-from-configmap=api-config --env-from-secret=postgres-credentials \
  -- python -m compute.jobs.daily_forecast --delivery-date 2026-05-01 --run-id mu-all-v1 \
  --map-run-id map-v1 --to-db
```

### Step 6 — Build and deploy

After step 2 has copied `compute/mu/mu_preds.npz`, build and deploy the image, then
deploy both cronjobs (`map_refresh_cronjob.yml`, `forecast_cronjob.yml`). The weekly map
append (step 1) and daily forecast (step 5) then keep everything current. A refreshed
residual pool requires another image build/deploy; normal daily appends do not.

### Good to know

* **Historic vs live cadence seam.** The backfill (step 3) refits on a 7-day grid and
  predicts the next 7-day block, so every historic day in `forecast_nodal` shares its
  week's single fit; the daily job (step 5) refits every day. Both are honest (the two
  `propagate_window` modes reconcile given identical inputs), but a historic panel row is
  not bit-for-bit "what the live job would have emitted that day."

---

ABLATION FULL RUN

```
docker compose run --rm compute python -m compute.mu.ablate \
    --score-from 2025-08-14 --preds-dir /compute/mu/ablation --out /compute/mu/ablation.csv

python -m compute.mu.outage_ablate --score-from 2025-08-14 --score \
    --preds-dir /compute/runs/outage_ablation \
    --out /compute/runs/outage_ablation.csv

```


Need to clean out memory

```
kubectl -n default scale \
    deploy/prometheus-kube-prometheus-operator --replicas=0
kubectl -n default scale \
    statefulset/prometheus-prometheus-kube-prometheus-prometheus --replicas=0
kubectl -n default scale \
    statefulset/alertmanager-prometheus-kube-prometheus-alertmanager --replicas=0
kubectl -n default scale \
    deploy/prometheus-grafana --replicas=0
```

Restart

```
kubectl -n default scale \
    deploy/prometheus-kube-prometheus-operator --replicas=1
kubectl -n default scale \
    deploy/prometheus-grafana --replicas=1
```

---


* `config.py`: config object that pulls from `/shared/settings.py`; kept to
  reduce changes during development.

* `constants.py`: carrers, regions, and `DEFAULT_P_MAX_PU` availability ceilings.
