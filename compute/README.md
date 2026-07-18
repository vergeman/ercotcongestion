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

Build and deploy in this order.

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
normal cheap append.

Hand-run the deployed cronjob on the identical path:
```
cd ops/deploy && source ../../.env && export IMAGE_TAG="$(cat ../../.image-tag)"
kubectl -n ercotstress create job --from=cronjob/ercot-map-refresh map-refresh-manual
```

### Step 2 — Historical backfill (seed the forecast history)

**Needs:** the map from step 1 (or `--fit-sf` to fit SF in-process instead).
**Does:** walks μ forward over all history, projects it through the map's per-week SF,
and bulk-loads the resulting nodal panel so the site has history on day one. Run **once
per model version** (`run_id`) — a past day never changes for a fixed run, and step 3
appends every new day going forward. Re-run only when the model version is bumped. The
full μ walk (command 1) is a prod-side operation (~16 GB).

```
# 1. walk-forward backtest → per-(hour,key) predictions (p_bind, mu_gbm)
#    --end is a fixed date, not today; pass a recent --end to reach current data.
python -m compute.mu.mu_model --preds-out /compute/mu/mu_preds.npz --end <YYYY-MM-DD>

# 2. project predictions through the map's SF → full-history nodal panel (P10/P50/P90 + point)
python -m compute.jobs.backfill_nodal --preds /compute/mu/mu_preds.npz \
    --nodal-out /compute/mu/mu_nodal.npz

# 3. bulk-seed forecast_nodal from the panel + flip the pointer (this mode does it itself —
#    no --to-db, which the CLI rejects here)
python -m compute.jobs.backfill_nodal --load-nodal-npz /compute/mu/mu_nodal.npz \
    --run-id mu-all-v1
```

`mu_nodal.npz` (~100 MB) is a throwaway intermediate — nothing reads it after command 3.
**`mu_preds.npz` is a live dependency**, not a seed artifact: the daily job (step 3)
loads it every run as the out-of-sample residual pool that draws the P10/P90 bands, and
it ships **baked into the image** (`Dockerfile: COPY compute/`; untracked in git, no
volume). It must be present and current at image-build time.

> **FOOTGUN — `--end` is a fixed default (`2026-07-01`), not "today."** `mu_model` and
> `backfill_nodal` never read the DB max or `now()`. Refreshing the residual pool means
> re-running command 1 with a recent `--end` (a date, not `tomorrow`) **and rebuilding /
> redeploying the image** — the daily job reads the baked-in copy, not one on disk. The
> scored walk begins at `--start + 240d` (the training warm-up), so the first residual
> week is ~8 months after `--start`.

### Step 3 — Daily forecast (append each new day)

**Needs:** a fresh map (step 1) and `mu_preds.npz` in the image (step 2).
**Does:** builds the panel at DAM-close vintage, refits the μ heads on the trailing
window and predicts D's 24 h, loads the map's latest causal SF window, projects μ through
it and draws the bands, writes `forecast_nodal` + `forecast_sf_artifact`, then flips
`forecast_current[ercot]` **last**. The SF loader is guarded: it takes the latest window
with `window_end ≤ D` and fails loud (prior pointer intact) if that window is missing,
stale (`D − window_end > 14d`), or covers `< 50%` of D's predicted binding mass — it
never serves stale geography. Peak ~16 GiB (the pod limit).

```
python -m compute.jobs.daily_forecast --delivery-date tomorrow --run-id mu-all-v1 --to-db
```

Gap-fill a single historic day — identical path, only the date changes (drop `--to-db`
for a dry run):
```
kubectl -n ercotstress run forecast-backfill-<DATE> --rm -it --restart=Never \
  --image="${IMAGE_REPO}/ercotstress/api-compute:${IMAGE_TAG}" \
  --overrides='{"spec":{"imagePullSecrets":[{"name":"regcred"}]}}' \
  --env-from-configmap=api-config --env-from-secret=postgres-credentials \
  -- python -m compute.jobs.daily_forecast --delivery-date 2026-05-01 --run-id mu-all-v1 --to-db
```

### Step 4 — Deploy

With steps 1–2 seeded, deploy both cronjobs (`map_refresh_cronjob.yml`,
`forecast_cronjob.yml`). The weekly map append (step 1) and the daily forecast (step 3)
then keep everything current with no redeploy.

### Good to know

* **Historic vs live cadence seam.** The backfill (step 2) refits on a 7-day grid and
  predicts the next 7-day block, so every historic day in `forecast_nodal` shares its
  week's single fit; the daily job (step 3) refits every day. Both are honest (the two
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
