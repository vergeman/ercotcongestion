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

## Runbook — serving the μ forecast + SF map

There are **two pipelines** over the shared upstream ERCOT DAM ingest
(`ercot_dam_shadow_prices`, `ercot_dam_spp`, `dam_system_lambda`, forecast vintages).
Since 0095-0002 they are **coupled in one direction**: the daily forecast reads the
weekly map's persisted SF (`implied_shift_factors`, `map-v1`) instead of refitting it,
so the **map must be built and fresh** for the forecast to run — a stale/missing map
fails the forecast loud (prior pointer intact), it never serves stale geography.

| | Forecast (the μ product) | Map (the SF explorer) |
|---|---|---|
| Cadence | daily 17:00 UTC | weekly, Sun 18:00 UTC |
| Cron | `ops/deploy/jobs/forecast_cronjob.yml` | `ops/deploy/jobs/map_refresh_cronjob.yml` |
| Entry | `compute.jobs.daily_forecast` | `compute.jobs.weekly_map` → `geo_persist` → `eval` |
| run_id | `mu-all-v1` | `map-v1` |
| Writes | `forecast_nodal`, `forecast_sf_artifact`, pointer `forecast_current[ercot]` | `implied_shift_factors`, `sf_window_meta` (incl. `sf_stability`), `constraint_geo` |
| Migrations | `30_forecast_nodal.sql`, `31_forecast_sf_artifact.sql` | `28`/`29` + the plan-0003 sf_* tables |

The map runner (`weekly_map`) is the sole SF fitter: it fits EVERY refit window across
history with `compute.sf.fit.implied_shift_factors` and persists each to
`implied_shift_factors`. `daily_forecast` reads the latest causal window from there
(`load_forecast_sf`) rather than refitting — one SF fit, shared. The μ heads (bind + μ)
are still **refit daily** inside `daily_forecast`; there is no separate weekly μ-model
refit. The only weekly job is the SF map.

### (A) One-time historical backfill — build the `*.npz`, seed `forecast_nodal`

This is the backfill. It computes the **past** nodal panel and bulk-loads it so the
site has history on day one. Run it **once per model version** (`run_id`), NOT on a
schedule: for a fixed `run_id` a past day never changes, and the daily job (B) appends
every new day going forward. Re-run only when the model version is bumped. The full
`mu_model` walk no longer fits a 16 GB node, so step 1 is a **prod-side** operation.

```
# 1. walk-forward backtest → per-(hour,key) predictions (p_bind, mu_gbm)
python -m compute.mu.mu_model --preds-out /compute/mu/mu_preds.npz

# 2. push predictions through the SF map → full-history nodal panel (P10/P50/P90 + point)
#    Reads the persisted map-v1 SF per week (causal window_end <= week), so a historic
#    day matches live (0095-0002); needs map-v1 built (step C). Add --fit-sf to refit
#    SF in-process instead (the pre-0002 self-contained path).
python -m compute.jobs.backfill_nodal --preds /compute/mu/mu_preds.npz \
    --nodal-out /compute/mu/mu_nodal.npz

# 3. bulk-seed the DB from the npz (no re-walk) + flip the pointer
python -m compute.jobs.backfill_nodal --load-nodal-npz /compute/mu/mu_nodal.npz \
    --run-id mu-all-v1 --to-db
```

What each `.npz` is: `mu_preds.npz` = the walk-forward booster predictions (already
out-of-sample honest); `mu_nodal.npz` (~100 MB) = the full-history nodal panel derived
from it. Neither is a live artifact — they are intermediates of the one-time seed.

### (B) Daily forecast job — appends tomorrow's day

One monolithic process: build panel at DAM-close vintage → `predict_day` (refit both
heads on the trailing window, predict D's 24 h) → load the weekly map's persisted SF
(`load_forecast_sf`, causal + freshness/coverage guarded) → forward `propagate_window`
(project μ through that SF, draw the bands) → write `forecast_nodal` +
`forecast_sf_artifact` → flip
`forecast_current[ercot]` **last**. Peak ~16 GiB (= the pod limit, no headroom); a
missing input fails loud and leaves the prior pointer intact. Deployed as
`forecast_cronjob.yml`; the daily tick runs:

```
python -m compute.jobs.daily_forecast --delivery-date tomorrow --run-id mu-all-v1 --to-db
```

Backfill / gap-fill a single historic day — identical path, only the date changes (drop
`--to-db` for a dry run):

```
kubectl -n ercotstress run forecast-backfill-<DATE> --rm -it --restart=Never \
  --image="${IMAGE_REPO}/ercotstress/api-compute:${IMAGE_TAG}" \
  --overrides='{"spec":{"imagePullSecrets":[{"name":"regcred"}]}}' \
  --env-from-configmap=api-config --env-from-secret=postgres-credentials \
  -- python -m compute.jobs.daily_forecast --delivery-date 2026-05-01 --run-id mu-all-v1 --to-db
```

### (C) Weekly SF map refresh — full-history re-run

The SF explorer only. Chains three steps in one container over full history under
`map-v1`. **FOOTGUN:** the runner calls `delete_sf_run(run_id)` first (wipes ALL windows),
then writes only `[--start, --end)` — `--start` MUST stay `2025-01-01` or served history
is silently deleted. There is no incremental append; a full re-run (~30 min / ~67M rows)
is how the latest window advances. Deployed as `map_refresh_cronjob.yml`.

```
python -m compute.jobs.weekly_map --run-id map-v1 --start 2025-01-01 --end <tomorrow> \
    --window-days 240 --refit-days 7 --ridge-lambda 1.0 --min-binding-hours 25 --persist-sf
python -m compute.sf.geo_persist --run-id map-v1
python -m compute.sf.eval --run-id map-v1 --start 2025-01-01 --end <tomorrow> \
    --window-days 240 --refit-days 7 --ridge-lambda 1.0 --min-binding-hours 25 --persist-eval
```

Hand-run the deployed cronjob on the identical path:

```
cd ops/deploy && source ../../.env && export IMAGE_TAG="$(cat ../../.image-tag)"
kubectl -n ercotstress create job --from=cronjob/ercot-map-refresh map-refresh-manual
```

### From 0 to live

1. Ingest cronjob already populating the DAM tables (upstream prerequisite).
2. Apply migrations 30/31 (+ 28/29 + sf_* for the map).
3. Run (C) once to seed the map tables — **now a prerequisite**, not optional: both
   the backfill (A, step 2) and the daily forecast (B) project through map-v1's
   persisted SF (0095-0002). (Use `--fit-sf` on A to seed without the map.)
4. Run (A) once to seed `forecast_nodal` history.
5. Deploy both cronjobs — (B) daily and (C) weekly then keep everything current with no redeploy.

### Cadence seam + known redundancies

Two properties of the current build are deliberate-or-tolerated, not bugs — do not
"fix" them by accident:

* **Historic vs live cadence seam.** The (A) backfill refits on a **7-day grid** and
  predicts the next 7-day block (`walk_forward`), so every historic day in
  `forecast_nodal` shares its week's single fit. The (B) daily job refits **every day**
  (`predict_day` = one-day block). So historic days and going-forward days are *not*
  constructed identically; there is a methodology seam at the backfill→live boundary.
  Both are honest (the 0013 reconciliation test pins that the two `propagate_window`
  modes agree given identical `wp`/`M`/`C`) — but don't read a historic panel row as
  "what the live job would have emitted that day."

* **SF fit once, shared across pipelines (0095-0002).** The forecast no longer refits
  SF on `[D−240, D)` every day. `daily_forecast` (and `backfill_nodal`, unless
  `--fit-sf`) read the map's persisted weekly SF from `implied_shift_factors`
  (`load_forecast_sf`, run `map-v1`) and project μ through it — the map fits this SF
  weekly with the identical `240/7/λ=1.0/25` config, and it is stationary within the
  7-day refit interval. This introduces a forecast→map dependency, guarded so it fails
  safe rather than serving stale geography: the loader takes the latest **causal**
  window (`window_end ≤ D`) and raises (prior pointer intact) if it is missing, stale
  (`D − window_end > 14d` — a missed weekly refresh), empty, or covers `< 50%` of D's
  predicted binding mass. Only the day's loaded matrix is still serialized into
  `forecast_sf_artifact`. The map runner keeps its own fit (it is the source).

* **Map runner re-fits its whole history weekly (waste, not decoupling).** Each (C) run
  `delete_sf_run(map-v1)` wipes all windows then refits every window from 2025-01-01,
  though every window except the newest is bit-identical to last week's. ~67M rows /
  ~30 min regenerated to add one window. There is no incremental append — the boundary
  grid is anchored at `--start` and persist is delete-all-then-copy. The real fix is
  "fit only new boundaries, upsert"; unsupported today, hence weekly + the `--start`
  footgun.

* **λ operating-point drift risk.** The adopted SF ridge is **λ=1.0** (`score.py:LAM`),
  but `compute.sf.fit.RIDGE_LAMBDA` still defaults to **1e-1**. `daily_forecast`/`backfill_nodal`
  get 1.0 via `score.py`; the map only gets 1.0 because both cronjobs pass
  `--ridge-lambda 1.0` explicitly. Drop that flag and the map silently fits at 1e-1 —
  the two pipelines would disagree. Keep the flag, or centralize the constant.

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
