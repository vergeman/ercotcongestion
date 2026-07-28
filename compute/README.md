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
| Cadence | weekly, Sun 18:00 UTC | daily ×2: final 17:00 UTC (h1) + preview 19:45 UTC (h2) |
| Cron | `ops/deploy/jobs/map_refresh_cronjob.yml` | `forecast_cronjob.yml` (final), `forecast_preview_cronjob.yml` (preview) |
| Entry | `weekly_map` → `geo_persist` → `eval` | `daily_forecast` |
| Writes | `implied_shift_factors`, `sf_window_meta`, `constraint_geo` | `forecast_nodal`, `forecast_sf_artifact`, pointer `forecast_current[ercot]` |

**μ vs SF — why they are separate.** The two are orthogonal and multiply. μ is the
*temporal* signal: per constraint, per hour, does it bind and how hard — driven by load,
weather, and outages, so it is refit **daily**. SF is the *spatial* map: constraint
shadow price → nodal congestion — grid geography that moves slowly, so it is fit
**weekly** on a 240-day window. Nodal congestion = SF · μ. The map is the sole SF fitter;
the forecast reuses its SF rather than refitting, so one weekly fit serves every daily
forecast.

> **Serving from a date `X`? Two shifts.** `X` can only be served once the week before
> it is built — μ needs that week as a residual seed, and the map needs a persisted SF
> window ending `≤ X`. So:
>
> * **Origin — one week back.** `weekly_map`, `eval`, `mu_model`, `score`, and
>   `backfill_nodal` take `--start = X − 7d` (an unserved pre-roll week). Only
>   `backfill_artifacts` (per-day) and the live daily job start at `X` itself.
>   (`load_scoreboard` has no `--start` — it just reshapes the CSVs it is handed.)
> * **Data — two weeks past the window.** Ingest every feed to
>   `origin − (train_days + 14) = origin − 254d` — 14 days (2 weeks) earlier than the
>   bare 240-day window (7 for μ's panel front-edge drop, 7 of step-3 alignment margin).
>
> Worked example, `target X = 2025-01-01`: **origin `2024-12-25`** for **steps
> 1–3**, for first served output `2025-01-01`, and ingest data floor
> **`2024-04-15`**. The unshifted commands below pass `X` directly as the
> origin, which instead serves from `X + 7d`.
>
> * Steps 1–3 (map, μ pool + score, nodal backfill) are start = target − 7. (2024-12-25)
> * The daily job (step 6) and `backfill_artifacts` (step 5) are start = target. (2025-01-01)
> * Data prior is − (240 + 14). (~ 2024-04-15)



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

> **Ingest `train_days + 14` back, not exactly `train_days`.** μ's covariate
> panel drops its first day(s) to DAM/tz edges, so aim the ingest floor at
> `origin − 247d` (`2024-04-25` for a 2025-01-01 origin). And then additional 7
> for downstream step 3 backfill_nodal alignment to `2024-04-18`. `mu_model`
> already reads from there; this just ensures the data is actually present.

Build and deploy in this order.

### Step 0 — Preflight

Apply the DB migrations (including `forecast_nodal`, `forecast_current`, and
`forecast_sf_artifact`) and ensure the shared DAM ingest is populated through the
historical end date selected below. The live daily job additionally needs D−1 DAM data
and D's forecast vintages available after DAM close. Run the following compute commands
in an environment with the production DB credentials.

### Dates in the runbook — what each flag controls

The stages take dates literally (they never read `now()` or the DB max). `--start`
now means the **same thing** in all three — the *series origin* — so one date
(**2025-01-01**, the product origin) drives the whole run:

* **`--start`** (`weekly_map`, `eval`, `mu_model`, `score`) — the *series origin*: the
  first day you want scored, **not** the data floor. Each stage extends the read back on
  its own (`weekly_map`/`eval`: `read_start = start − window_days`; `mu_model`:
  `start − train_days − leadin`), so `--start 2025-01-01` scores from 2025-01-01
  while reading whatever history it needs behind that. Leave it at the product
  origin; you never hand-compute a data floor.
* **`--score-from`** (`mu_model`, optional) — overrides *only* the scored-grid phase
  and defaults to `--start`. Rarely needed — set it only to pin a phase different
  from the origin (e.g. an ablation on a specific sf week).
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
    --window-days 240 --refit-days 7 --ridge-lambda 1.0 --min-binding-hours 25 --persist-sf \
    --rebuild
```

* `compute.jobs.weekly_map`: `--start` is the series origin. Add `--rebuild` to
wipe the run and refit from scratch (~30 min / ~67M rows); omit it for the
normal cheap append. **Extending the ingest floor backward** — the initial
2024-05-06 build that fills the 2025-01-01 → 2025-08 windows — is a from-scratch
case: pass `--rebuild`, since a plain append only fits *forward* boundaries it
does not already have.

* `--persist-sf`: `implied_shift_factors` stored in db:

```
MAP_RUN_ID=map-v1

python -m compute.sf.geo_persist --run-id map-v1

python -m compute.sf.eval --run-id map-v1 --start 2025-01-01 --end <tomorrow> \
    --window-days 240 --refit-days 7 --ridge-lambda 1.0 --min-binding-hours 25 --persist-eval
```

* `diagnostics_<yyyymmdd>.json` and `eval.csv` artifacts in
  `/compute/runs/<run_id>`.


### Step 2 — Build the μ residual pool and score inputs

**Does:** walks μ forward over history and writes out-of-sample `(p_bind, mu_gbm)`
predictions, then scores them into the per-`(week × source × regime)` currencies. The
predictions are both the input to the historical nodal backfill and the residual pool
used to draw P10/P90 bands in the daily job; the score CSV feeds the R5 verdict
(step 3) and the weekly scoreboard (step 4). Prod-side (~16 GiB).

Use `mu-all-v1` for every forecast artifact and DB write. The SF map deliberately has
its own run ID, `map-v1`.

`--run-id` is the canonical namespace (plan/0113): `mu_model` derives its outputs
under `runs/<run-id>/mu/` (`mu_weekly.csv`, `mu_preds.npz`) and creates that tree
itself — no `ART_DIR` / `mkdir`. `compute.mu.score` has no `--run-id`, so point it at
the same derived paths explicitly; it writes `mu/mu_score_weekly.csv` (the *score*
schema — a different file from `mu_model`'s `mu_weekly.csv` calibration output).

```
# --start is the series origin (product origin, 2025-01-01) — the same date the SF
# map used; mu_model derives its own read floor (start − train_days − leadin). --end
# is a fixed recent completed date — see "Dates in the runbook".
# YYYY-MM-DD: tomorrow

RUN_ID=mu-all-v1
MU_SPILL_DIR=/compute/runs/__spill__

python -m compute.mu.mu_model --run-id ${RUN_ID} \
    --start 2025-01-01 --end <YYYY-MM-DD>

python -m compute.mu.score \
    --preds /compute/runs/${RUN_ID}/mu/mu_preds.npz \
    --out   /compute/runs/${RUN_ID}/mu/mu_score_weekly.csv \
    --start 2025-01-01 --end <YYYY-MM-DD>
```

**`mu_preds.npz` is a live dependency**, not merely a seed artifact: the daily job
loads it every run as the out-of-sample residual pool that draws the P10/P90 bands.
It lives on the **`compute-runs` PVC** (`ops/deploy/base/compute/runs-pvc.yml`,
mounted at `/compute/runs`), and the daily job resolves it **by run ID** —
`runs/<run-id>/mu/mu_preds.npz`, the same path `mu_model --run-id` just derived.
Writing it there on that PVC is all that is needed; **refreshing the pool is a file
drop, not an image rebuild** (override the path with `daily_forecast --preds` if
ever needed). Any pod that runs `daily_forecast` must mount the PVC — the daily
cronjob does (`forecast_cronjob.yml`); hand-runs must too (see Step 6).

> **FOOTGUN — `--end` is a fixed default (`2026-07-01`), not "today."** `mu_model` and
> `backfill_nodal` never read the DB max or `now()`. With `--score-from` set (above),
> the scored walk begins there; without it, the walk begins at `--start + 240d` (the
> training warm-up), so the first residual week is about eight months after `--start`.

### Step 3 — Historical nodal-price backfill

**Needs:** step 1's persisted `map-v1` and step 2's predictions + score CSV.
**Does:** projects every eligible walk-forward prediction through its causal persisted
SF window, writes the P10/P50/P90/point panel for `mu-all-v1`, then promotes that same
run only after the bulk write succeeds. This is the historical price backfill.

With `--run-id ${RUN_ID}` every path derives (plan/0113): the residual pool and score
CSV are read from `runs/${RUN_ID}/mu/`, and the bands CSV + nodal panel are written to
`runs/${RUN_ID}/forecast/` (`mu_bands_weekly.csv`, `mu_nodal.npz`) — the job creates
that tree itself. Pass `--preds` / `--scores` / `--out` / `--nodal-out` only to point
somewhere else.

```
set -o pipefail

python -m compute.jobs.backfill_nodal \
    --run-id "${RUN_ID}" --map-run-id "${MAP_RUN_ID}" \
    --end <tomorrow YYYY-MM-DD> \
    --to-db 2>&1 | tee -a "$RUN_ID/backfill_nodal.log"
```

`--to-db` requires `--run-id` (which derives `--nodal-out`) or an explicit
`--nodal-out`. `mu_nodal.npz` is the audit/reload artifact for the seed. Do not run
`--load-nodal-npz` after the command above: it only reloads that same panel. Use it
only to restore an existing NPZ into a fresh DB:

```
python -m compute.jobs.backfill_nodal --run-id "${RUN_ID}" \
    --load-nodal-npz /compute/runs/${RUN_ID}/forecast/mu_nodal.npz
```

This fast historical path writes `forecast_nodal`, but does not write
`forecast_sf_artifact`: it does not invoke `daily_forecast` once per day.

### Step 4 — Load the weekly scoreboard

**Needs:** step 2's score CSV (`mu/mu_score_weekly.csv`) and step 3's bands CSV
(`forecast/mu_bands_weekly.csv`).
**Does:** joins the two weekly CSVs and COPYs them into `scoreboard_weekly` under
`${RUN_ID}`, so the API serves indexed board rows rather than files. Reshape-and-serve,
not new measurement — the numbers are transcribed as-is. Idempotent by
delete-then-copy scoped to `run_id`.

With `--run-id ${RUN_ID}` both inputs derive from `runs/${RUN_ID}/` (plan/0113); pass
`--score` / `--bands` only to override.

```
python -m compute.jobs.load_scoreboard --run-id "${RUN_ID}"
```

### Step 5 — Optional production-equivalent historical artifact backfill

Step 3 fills prices (`forecast_nodal`) but **not** the per-day SF+μ artifact
(`forecast_sf_artifact`) — the object the constraint-explorer panel reads
(`/map/constraints/ranked`). So on a fresh backfill that panel 503s for every historical
date until this step runs; only live days (step 6) have the artifact otherwise.

`backfill_artifacts` loops the daily job's exact path over a date range: for each UTC
delivery date it refits the daily μ model, **replaces that date's nodal rows** with the
production-equivalent per-day fit, and writes its `forecast_sf_artifact`. It is much more
expensive than step 3 (a per-day refit, ~16 GiB each, vs. one weekly fit shared across 7
days), so it is optional and intentionally not the default history seed.

```
set -o pipefail

MU_SPILL_PANEL=1
MU_SPILL_DIR=/compute/runs/__spill__

python -m compute.jobs.backfill_artifacts --run-id "${RUN_ID}" --map-run-id "${MAP_RUN_ID}" \
    --start 2025-01-08 --end <YYYY-MM-DD> --no-skip-existing --to-db \
    2>&1 | tee -a "$RUN_ID/backfill_artifacts.log"
```

* **Resumable** — skips dates already in `forecast_sf_artifact` (pass `--no-skip-existing`
  to rewrite), so an interrupted run continues where it stopped.
* **Fail-soft** — a date without complete DAM-close inputs or a causal map window is logged
  and skipped (`--stop-on-error` aborts instead). Early dates with no causal window are the
  common expected skip, so start `--start` at/after the first served week.
* **Pointer** — like the daily job, each day flips `forecast_current[ercot]` to `--run-id`;
  the tool warns loudly at startup if that is not the promoted run. **Do not mix a different
  run ID into one range.** Add `--npz-dir` only when it names a persistent mounted directory;
  it is not required for the DB artifacts.

For a single date, `--start`/`--end` may be the same day (equivalent to one
`daily_forecast --delivery-date` run).

### Step 6 — Daily forecast (append each new day)

**Needs:** a fresh map (step 1) and `mu_preds.npz` on the `compute-runs` PVC at
`runs/<run-id>/mu/` (step 2), with the PVC mounted at `/compute/runs`.
**Does:** builds the panel at DAM-close vintage, refits the μ heads on the trailing
window and predicts D's 24 h, loads the map's latest causal SF window, projects μ through
it and draws the bands, writes `forecast_nodal` + `forecast_sf_artifact`, then flips
`forecast_current[ercot]` **last**. The SF loader is guarded: it takes the latest window
with `window_end ≤ D` and fails loud (prior pointer intact) if that window is missing,
stale (`D − window_end > 14d`), or covers `< 50%` of D's predicted binding mass — it
never serves stale geography. Peak ~16 GiB (the pod limit).

**When you run it does not change what it produces.** Don't start before 10:00 CT on D-1
(DAM close) — the covariates aren't there yet and the job fails loud. After that, any
time is fine. Running at 16:00 CT gives the same panel as running at 12:00 CT, and a
backfill of an old day gives what that day would have produced live.

This surprises people, because ERCOT publishes D's own DAM prices at 13:30 CT on D-1, so
a late run *looks* like it could peek. It can't: the reads are bounded by the data, not
by the clock. Covariates filter on `posted_datetime` against DAM close (`features.py`),
and prices are read with `interval_ts < D` (`panels.py`), which is what keeps D's own
prices out. Neither depends on when the job fires.
(`test_reads_and_propagation_touch_no_interval_at_or_after_D` pins this.)

A late run is still worth noticing — it usually means the schedule or ingest has drifted
— but it is not a correctness problem, so the job doesn't refuse.

The cron fires at 17:00 UTC = 12:00 CDT / 11:00 CST, past DAM close in both DST states.
`tomorrow` means the next **CT** date. The run logs the delivery date it resolved along
with its CT hour span — 19:00 → 18:00 CT in summer, because the delivery day is a UTC
calendar day — plus its `horizon`, `map_run_id`, and the SF `window_end` it projected
through (so a preview-vs-final diff contaminated by a weekly map refit is identifiable).

```
python -m compute.jobs.daily_forecast --delivery-date tomorrow --run-id mu-all-v1 \
    --map-run-id map-v1 --to-db
```

**Two horizons — final and preview (0123).** The forecast runs *twice* a day, same
model version (`--run-id` unchanged — it scopes MODEL VERSION only, not the day or the
horizon). `--horizon` is the only difference; horizon is a persistence/labeling
property, so the fit is byte-identical at both — only the vintaged forecast covariates
on the prediction row differ.

| | Final (h1) | Preview (h2) |
|---|---|---|
| Tick | 17:00 UTC (`forecast_cronjob.yml`) | 19:45 UTC (`forecast_preview_cronjob.yml`) |
| `tomorrow` resolves to | T+1 (next CT date) | T+2 (two CT dates out) |
| Timing vs D's DAM | ~2h AFTER D's DAM closed — verification-only | inside D's decision window, ~20h before D's DAM closes |
| DAM-publication gate | none (D−1 closed hours ago) | asserts D−1's `ercot_dam_shadow_prices` exist BEFORE the fit; missing → fail loud, nothing written |
| Immutability | replace-in-place per re-run | **never overwritten by the final** — `final − preview` is a preserved audit trail |
| Scoreboard | its own track | its own independent track (graded per horizon) |

Serving coalesces the two into one continuous series (prefer final, fall back to
preview) with zero web changes; `/forecast_range` reports per-day `horizons`
provenance and accepts `?horizon=` to read one track explicitly (the "what changed"
view). See `plan/0123-forecast-horizon-preview.md`.

```
# the preview tick — identical path, add --horizon 2
python -m compute.jobs.daily_forecast --delivery-date tomorrow --run-id mu-all-v1 \
    --horizon 2 --map-run-id map-v1 --to-db
```

**Grading is embedded — not a separate step.** After a successful publish and pointer
flip, `daily_forecast` calls `grade_day` itself to grade the most recent
fully-realized served day **on its own horizon's track** — the final tick grades the
h1 scoreboard, the preview tick the h2 scoreboard, two independent tracks per run_id
(0123). Run `grade_day` standalone **only** to retry a day whose grade failed or was
skipped (never as a duplicate routine step); `--horizon` selects the track (default 1):

```
python -m compute.jobs.grade_day --delivery-date auto --run-id mu-all-v1 --to-db
python -m compute.jobs.grade_day --delivery-date auto --run-id mu-all-v1 --horizon 2 --to-db
```

Gap-fill a single historic day — identical path, only the date changes (drop `--to-db`
for a dry run). Old days need no special flag; see "When you run it does not change what
it produces" above. Add `--force` to overwrite a day already published under this
`--run-id` — without it the job stops before doing any work. The pod **must mount the
`compute-runs` PVC** at `/compute/runs` so the
job can read the residual pool; because the override supplies `volumes`, it also has to
specify the container fully (image, command, env), so the top-level `--image` /
`--env-from-*` flags no longer drive it:
```
kubectl -n ercotstress run forecast-backfill-<DATE> --rm -it --restart=Never \
  --image="${IMAGE_REPO}/ercotstress/api-compute:${IMAGE_TAG}" \
  --overrides='{
    "spec":{
      "imagePullSecrets":[{"name":"regcred"}],
      "volumes":[{"name":"runs","persistentVolumeClaim":{"claimName":"compute-runs"}}],
      "containers":[{
        "name":"forecast-backfill",
        "image":"'"${IMAGE_REPO}"'/ercotstress/api-compute:'"${IMAGE_TAG}"'",
        "envFrom":[{"configMapRef":{"name":"api-config"}},{"secretRef":{"name":"postgres-credentials"}}],
        "volumeMounts":[{"name":"runs","mountPath":"/compute/runs","readOnly":true}],
        "command":["python","-m","compute.jobs.daily_forecast",
                   "--delivery-date","2026-05-01","--run-id","mu-all-v1",
                   "--map-run-id","map-v1","--to-db"]
      }]
    }
  }'
```
Simpler alternative: `exec` into the `compute-shell` pod (`ops/deploy/compute_shell.sh`),
which already mounts the PVC, and run the `python -m compute.jobs.daily_forecast …`
command there.

### Step 7 — Build and deploy

Build and deploy the image, then deploy every cronjob (`map_refresh_cronjob.yml`,
`forecast_cronjob.yml`, `forecast_preview_cronjob.yml`) and the `compute-runs` PVC
(`ops/deploy/base/compute/runs-pvc.yml`) if not already applied — `./model_cronjobs.sh
all` applies all three. The weekly map append (step 1) and the two daily forecast ticks
(step 6) then keep everything current. The residual pool now lives on the PVC (step 2),
so refreshing it is a file drop on `/compute/runs` — **no image rebuild required**; only
a code or dependency change needs a new image.

Hand-run the deployed cronjobs on the identical path:
```
cd ops/deploy && source ../../.env && export IMAGE_TAG="$(cat ../../.image-tag)"
kubectl -n ercotstress create job --from=cronjob/ercot-map-refresh
kubectl -n ercotstress create job --from=cronjob/ercot-forecast
kubectl -n ercotstress create job --from=cronjob/ercot-forecast-preview
```


### Good to know

* **Historic vs live cadence seam.** The backfill (step 3) refits on a 7-day grid and
  predicts the next 7-day block, so every historic day in `forecast_nodal` shares its
  week's single fit; the daily job (step 6) refits every day. Both are honest (the two
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
