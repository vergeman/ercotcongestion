# Scoring: what gets graded, by what, and where

Three different things in this project are called "the grade" or "the scoreboard."
They measure different quantities, come from different pipelines, and are *not*
comparable to each other. This document lines each one up with the job that
writes it, the table it lands in, and the endpoint that serves it.

Serving uses one deterministic forecast: `point = −(E_mu · SF)`, where
`E_mu = p_bind × mu_gbm`. Walk-forward `mu_preds.npz` remains offline-only for μ
evaluation. The retired simulated P50 achieved $3.185/MWh h1 trailing-90-day MAE
versus $3.229/MWh for point (1.36%); its nine high-congestion h1 days had a 4.64%
advantage. That did not justify the residual-pool dependency or inconsistent UI.

If you are looking at a number and want to know what it means, start with the
table in [The three surfaces](#the-three-surfaces).

## Vocabulary

Enough to read the rest of this page.

* **Delivery day** — one ERCOT trading day, cut at midnight America/Chicago
  (05:00Z→05:00Z in CDT, 06:00Z→05:00Z in CST). **23, 24, or 25 hours long**
  depending on DST; see [Gotchas](#gotchas). Stored as true UTC instants; the
  day boundary is a CT concept applied at the edges.
* **μ (mu)** — a transmission constraint's shadow price. The model forecasts μ per
  constraint per hour; congestion at a node is μ projected through that node's
  shift factor.
* **SF (shift factor)** — how much a given constraint's price lands on a given
  node. `SF < 0` = import = red, `SF > 0` = export = blue (see `docs/SF.md`).
* **Point forecast** — the single deterministic congestion number per (hour, node):
  `−(E[μ]·SF)`. Point metrics are `mae`, `pooled_r2`, and `rank_spearman`.
* **Horizon** — how far ahead the forecast fired. **h1** is the final forecast
  (fires 17:00Z on D−1, after DAM close). **h2** is the preview (fires 20:15Z on
  D−2, before D's DAM auction clears, so it is genuinely disadvantaged).
* **Backtest** — running the recipe over history *as if live*, to measure it before
  trusting it. "Backtest" here always means the offline walk-forward: fit only on
  what was knowable at each point, predict forward, score against what actually
  happened. It is not a fit to history and not a replay of stored predictions —
  the numbers are what the recipe would have produced had it been running.
* **Walk-forward** — repeated fit-then-predict marching through time: fit on the
  trailing window ending at D, predict D, score it, advance D one day, repeat. No
  fold ever sees data after its own D, so the accumulated score is what you would
  have gotten running live over that span.
* **OOS (out-of-sample)** — scored on data outside the fit's training window. Every
  prediction in a walk-forward is OOS by construction.
* **Residual** — the error of one prediction: `realized − predicted`. The
  **walk-forward predictions** are the offline backtest artifact, which
  the forward run samples to draw the P10/P90 band around each point. It is
  filtered to weeks strictly before D (`daily_forecast.py:350`), so a day's band
  is never widened or narrowed by its own outcome. Point forecasts do not depend
  on it; `coverage80` / `pinball` do.
* **Ridge λ** — the L2 penalty on the standardized shift-factor solve,
  `RIDGE_LAMBDA = 1.0` (`compute/sf_map/config.py`). Constraints and nodes are
  badly collinear; the penalty keeps the fitted SFs stable instead of letting two
  near-identical nodes trade enormous offsetting coefficients. Single-sourced in
  `compute/sf_map/config.py` so the μ forecast and the SF map cannot drift.
* **Feature set / arms** — an *arm* is a group of covariates sharing a column
  prefix, and a *feature set* is a named combination of arms
  (`compute/mu_forecast/model/runner.py`):

  | Arm | Prefix | What it carries |
  |---|---|---|
  | `lag` | `lag_` | lagged realized μ — the persistence content |
  | `geo` | `geo_` | constraint geography via the \|SF\| centroid |
  | `wx` | `wx_` | per-constraint weather-response vectors |
  | `out` | `out_` | per-constraint generation-outage exposure |

  The shipped configuration is `--features all` = `("lag", "geo", "wx")`
  (`DEFAULT_ARMS`, `daily_forecast.py:102`). `out` exists but is not shipped — it
  graded flat. The panel is built once and an arm is a *column mask* over it, so
  "the only thing that varies is the feature set" is a property of the code, not
  a claim.
* **Recipe** — the configuration *and* the procedure it drives: `train_days=240`,
  ridge λ, the feature set, the arms, plus **"refit daily, propagate through a
  weekly SF map"** — i.e. the μ heads are re-estimated from scratch for every
  delivery day on that day's trailing 240 days, and their per-constraint output
  is then pushed out to per-node dollars through an SF map that is only re-fit
  weekly. The backtest validates this whole thing, not a stored parameter vector.

## The three surfaces

| Surface | Written by | Source of truth | Horizon-aware? | Served at |
|---|---|---|---|---|
| `scoreboard_weekly` | `load_scoreboard` | **offline backtest CSVs** (`mu_score_weekly.csv`) | **no such column** | `/scoreboard/weekly`, `/scoreboard/headline` |
| `scoreboard_daily` | `grade_day.py` | live nodal — what was actually served | yes | `/scoreboard/daily` |
| `analysis_grade_daily` | `materialize_brief_grade` | `forecast_sf_artifact` | yes | `/analysis/grade`, `/analysis/grade-history` |

Prod coverage as of 2026-08-19, to give a feel for the shapes:

| Surface | Coverage |
|---|---|
| `scoreboard_weekly` | 2025-01-01 → 2026-07-15, 5 sources × ~80 weeks × regimes |
| `scoreboard_daily` | h1 2026-07-20→08-18 (30d) · h2 2026-07-31→08-19 (20d) |
| `analysis_grade_daily` | h1 2025-01-01 → 2026-08-18 · h2 2026-07-30 → present |

### 1. `scoreboard_weekly` — "does the model work?"

**Graded thing:** nodal congestion in $/MWh. The model's E[μ] projected through the
SF map to every settlement point, versus realized `SPP − system_λ`.

**Metrics:** `pooled_r2`, `mae`, `rank_spearman`, `sign_agree`, `topdecile_hit`,
plus P50 band quality (`coverage80`, `band_width`, `pinball`).

**Provenance:** a pre-registered **offline walk-forward backtest**. `load_scoreboard`
is explicit that it is "Reshape-and-serve, NOT new measurement" — it transcribes
`mu_score_weekly.csv` as-is and "never redefines a gate or re-measures a baseline."

Sliced by week × source × regime, five sources: `model`, `persistence`,
`climatology`, `oracle`, `null`. This is the months-long "model efficacy" view, and
it is an evaluation of the **model**, not of the live service. It has no `horizon`
column at all, which is why it can span 19 months while the live preview track only
goes back a few weeks.

#### Where `mu_score_weekly.csv` comes from

The weekly board is the tail of an **offline, manually-run chain**. Nothing in the
daily cron touches it. Everything lives on the runs PVC under
`compute/runs/<run-id>/` (`RUNS_ROOT`, `backfill_nodal.py:48`):

```
compute.mu_forecast.model.backtest  (walk_forward) -> runs/<run-id>/mu/mu_preds.npz
    the walk itself: refit every 7 days (REFIT_DAYS) on the trailing 240d and predict
    the next week — ~83 folds over 19 months, not one per day — keeping the OOS preds

compute.evaluation.mu --preds mu_preds.npz   -> runs/<run-id>/mu/mu_score_weekly.csv
    scores those preds into two currencies per (week x source x regime):
    magnitude (pooled_r2, mae) and screening (rank_spearman, sign_agree, topdecile_hit)

compute.jobs.backfill_nodal                  -> runs/<run-id>/forecast/mu_nodal.npz
    deterministic −(E_mu · SF) historical nodal point panel

compute.jobs.load_scoreboard --run-id ...    -> scoreboard_weekly  (the DB table)
    delete-then-copy, scoped to run_id; transcription only
```

**What maintains it now: nothing.** The board is frozen at its last walk (2026-07-15
on prod as of this writing) and will stay there. The deployed crons are `ercot-ingest`
(*/15), `ercot-forecast` (17:00Z), `ercot-forecast-preview` (20:15Z) and
`ercot-map-refresh` (Sundays 18:00Z) — none of them run a walk. Advancing the weekly
board means re-running the walk offline and re-loading it; re-running
`load_scoreboard` alone just re-transcribes the same CSVs. That is by design: the
walk is a pre-registered evaluation, not a live metric. Live behavior is what
`scoreboard_daily` is for.

#### Refreshing the weekly board

There is no backfill job for this board — you re-run the walk and reload it. Four
steps, in order, all on the runs PVC:

```bash
# 1. the walk (the expensive step) — refits weekly, chunked to bound memory
python -m compute.mu_forecast.model.backtest --run-id mu-all-v1 \
    --start 2025-01-01 --end 2026-08-01 --features all --chunk-weeks 32

# 2. score the OOS predictions into the weekly currencies
python -m compute.evaluation.mu --preds runs/mu-all-v1/mu/mu_preds.npz \
    --out runs/mu-all-v1/mu/mu_score_weekly.csv

# 3. band metrics for the P50 track
python -m compute.jobs.backfill_nodal --run-id mu-all-v1

# 4. transcribe into the DB (delete-then-copy, scoped to run_id)
python -m compute.jobs.load_scoreboard --run-id mu-all-v1
```

Only step 4 touches the database, and it replaces that run's board cleanly, so the
board is stale-but-consistent right up until the moment it is current.

**Cost.** The walk is far cheaper than a per-day artifact backfill — it refits once
per week, so ~83 fits for 19 months against ~575 for the artifacts — but each fit is
the same order of work, and the panel build (~10M rows, the package's peak-memory
line) runs once per chunk. Order of hours, not minutes; no measured figure is recorded
anywhere, so time one chunk before planning around it. `--chunk-weeks` is the memory
knob, and `mu_preds.npz` lands at a few GB.

**A re-run will not reproduce the current board.** 0133 moved the walk's scored grid
onto the CT day boundary (the `score_from_ts` tz fix), so a walk on HEAD is phased
differently from the loaded board, which was produced before that change. That is a
reason to re-run — the board on prod describes a grid the service no longer uses — but
it means the new numbers are a new series, not a continuation. Re-running under the
same `run_id` overwrites the old board; use a fresh `run_id` to keep both.

### 2. `scoreboard_daily` — "did what we actually served hold up?"

**Graded thing:** identical currency to #1, deliberately. `grade_day.py` uses "the
**same `score_matrix`** the backtest uses, so a live number and a backtest number
are the same currency."

**What changes is the subject.** Not a walk — the point forecast the service really
published, read back out of `forecast_nodal`:

> the `model` source is graded on the served point — the honest out-of-sample
> product. The comparators are recomputed on D "for context"

All sources are scored on the same node intersection so `model − persistence` is
apples-to-apples, and the `null` (flat) source is an integrity tripwire: a flat map
ranks nothing, so a `null` that scores above chance means the metric path regressed.

So #1 and #2 are the same ruler applied to two different things: the pre-registered
walk versus the artifact that actually went out the door.

### 3. `analysis_grade_daily` — "was the Brief's story right?"

**Different currency entirely.** No $/MWh error anywhere. It grades *rankings and
shapes* derived from the artifact's `E_mu` (`compute/analysis/grade.py`):

* **Detection** — average precision over the daily constraint ranking. Did the right
  constraints surface, in the right order?
* **Magnitude** — soft overlap of the daily Σμ vectors. Was the shape of the day's
  congestion right?
* **Timing** — chance-adjusted average precision over pooled constraint-hours. Right
  constraint, right hour?

Scored against yesterday-repeated settlement (`persistence`) and `climatology` on the
same full universe, with two subjects per day: `constraints` and `nodes`.

`materialize_brief_grade` draws the line itself: `scoreboard_daily` "uses a different,
nodal scorecard currency and **must not be substituted for** the Brief's
Detection/Magnitude/Timing cards."

## Is anything grading h2 against h1?

**No — not as a head-to-head.** Each horizon is graded independently against its own
baselines, on both horizon-aware surfaces:

* `scoreboard_daily` carries `horizon` in its primary key, so `grade_day` writes a
  separate row set per horizon per day.
* `analysis_grade_daily` likewise; `/analysis/grade` and `/analysis/grade-history`
  take a `horizon` parameter and resolve one track at a time.

Nobody computes an "h1 vs h2" delta, and no view puts the two series side by side.
The comparison you would want — *how much does the extra day of information buy?* —
has to be made by eye, or by querying both horizons for the same dates:

```sql
SELECT delivery_date, horizon, mae, rank_spearman
FROM scoreboard_daily
WHERE run_id = 'mu-all-v1' AND source = 'model'
ORDER BY delivery_date, horizon;
```

> **Fixed 2026-08-19.** `/scoreboard/daily` previously had no horizon predicate —
> `FROM scoreboard_daily WHERE run_id = %s` — and `DailyPoint` carried no horizon
> field. Once the preview cron began grading there were two rows per
> (delivery_date, source), so the endpoint returned both and the page kept
> whichever arrived last, meaning the live board could show a **preview** grade
> labeled as the served forecast. The endpoint now resolves and filters a single
> horizon (defaulting to the final track, falling back to whatever the run has
> graded), returns `horizon` on every point plus a `horizons` list, and the page
> carries a track selector that is labeled even when only one track exists.

## Reading the Scoreboard page

The page stacks four blocks that look alike (tiles, tiles, chart, table) but answer
different questions over different spans. Each now carries a header saying which.
Top to bottom:

| Block | Header | Endpoint → table | Span | What it says |
|---|---|---|---|---|
| 4 tiles | **Live · per-delivery-day grade** | `/scoreboard/daily` → `scoreboard_daily` | **one** delivery day, one horizon (both selectable) | how the forecast we actually served did on that day |
| 3 tiles | **Backtest · rolling 90-day headline** | `/scoreboard/headline` → `scoreboard_weekly` | the last 90 days of the walk | the backtest's recent form, pooled |
| line chart | **Backtest · weekly series** | `/scoreboard/weekly` → `scoreboard_weekly` | every week of the walk | week-by-week trend, 4 sources |
| table | **Backtest · pooled over all weeks, split pre/post-RTC+B** | same weekly payload (`splits`) | **lifetime** of the walk | the whole-history verdict, and whether RTC+B changed it |

For the job behind each block and how often it moves, see
[Which panel comes from which job](#which-panel-comes-from-which-job).

Specifics that are easy to misread:

**The two tile rows are not the same thing.** The top row is *live* — one served day,
four currencies (Rank ρ, Sign Agreement, Top-Decile Hit, Pooled R²), read from
`scoreboard_daily`. The second row is *backtest* — three screening currencies pooled
over a rolling 90-day window of `scoreboard_weekly`
(`HeadlineTiles` picks `window_days === 90`). Same tile shape, same colors,
deliberately: a live number and a backtest number are the same currency. But the top
row moves every day and the second row only moves when a new walk is loaded.

**The 90-day headline is computed per request, not on a schedule.** `_build_windows`
pools the weekly rows in memory each time the endpoint is called: it takes `as_of` =
the board's most recent week, keeps the weeks inside the trailing window (30 and 90
days are both built; the page shows 90), and averages each source's cells weighted by
`n_hours`. Nothing materializes it, and no job "runs every 90 days" — it is a
look-back over `scoreboard_weekly`, so it changes only when that table changes, i.e.
when a new walk is loaded. On a static board it returns the same numbers forever.

**Both tile rows read model-with-comparators, never a lone figure.** The big number
is the model; `▲ vs persist` is the model−persistence delta (positive = model wins,
since all four are higher-is-better); `ceiling` is the oracle.

**The chart ends where the walk ended.** Its last week is 2026-07-15 because that is
the last week in `scoreboard_weekly`, and nothing advances that table on a schedule —
see [Where `mu_score_weekly.csv` comes from](#where-mu_score_weeklycsv-comes-from).
It is not a data outage, and re-running the daily jobs will not extend it.

**The bottom table is lifetime, not "most recent week."** Three rows — All weeks,
Pre-RTC+B, Post-RTC+B — each with its week count, pooled across the whole walk for
whichever metric is selected. RTC+B (2025-12-05) is the market's structural break;
the split exists so a pre-break result cannot be quietly carried through it.

**The metric buttons drive the chart and the table only.** `Rank ρ / Sign Agreement /
Top-Decile Hit` are the screening group; the toggle swaps in the magnitude group
(`Pooled R² / MAE`). Neither tile row responds to it — both are fixed sets.

**The Net-load Bucket selector filters the backtest sections only.** The live board
has no regime dimension; the server ignores `regime` for that section, so the top
tiles are unchanged by it even though the control sits in their header.

**Two selectors, two meanings, both in the live header.** The delivery-day dropdown
picks which served day the top tiles grade. The track dropdown picks the horizon —
`Final · fires D−1` versus `Preview · fires D−2`. When a run has graded only one
track, the label still shows, so a tile is never ambiguous about its vintage.

## Which panel comes from which job

Every panel below is one dataset, advanced by one job. The live tick
(`daily_forecast.main`, once per horizon) does four things in order, each fail-soft
after the publish is committed:

```
1. fit + publish   (persist_forecast)   -> forecast_nodal, forecast_sf_artifact  (D)
2. rollup          (persist_rollup)     -> forecast_constraint_daily             (D)
3. grade_day                            -> scoreboard_daily      \  latest still-
4. materialize_day (Brief grade)        -> analysis_grade_daily  /  ungraded day
```

"The rollup" always means step 2: reducing an artifact's `E_mu` to one Σμ +
nonzero-hour count per constraint. Live it is `persist_rollup` inside the tick; over
a date range it is the `backfill_forecast_history` job. Same function, same rows,
same table — one is called with today's artifact, the other in a loop over history.

Steps 2–4 are non-fatal by contract: a failure logs, rolls back, and the next tick
retries, because `grade_day` is idempotent and `resolve_gradeable_date` self-selects
the oldest ungraded day. So every artifact-backed panel self-heals on a daily cadence.
**Only `scoreboard_weekly` is outside this loop** — nothing schedules it.

### Scoreboard page

| Panel | Dataset | Advanced by | Cadence | Backfilled by |
|---|---|---|---|---|
| Live · per-delivery-day grade (4 tiles) | `scoreboard_daily` | `grade_day`, step 3 of the tick | daily, one day per tick | **no bulk CLI** — `grade_day --delivery-date` one day at a time |
| Backtest · rolling 90-day headline (3 tiles) | `scoreboard_weekly` | `load_scoreboard` (window pooled per request) | **manual only** | re-run the offline walk, then reload |
| Backtest · weekly series (chart) | `scoreboard_weekly` | `load_scoreboard` | **manual only** | same |
| Backtest · pooled pre/post-RTC+B (table) | `scoreboard_weekly` (`splits`) | `load_scoreboard` | **manual only** | same |

The three backtest panels share one payload, so they always move together — and they
have not moved since the last walk (2026-07-15 on prod). To advance them, see
[Refreshing the weekly board](#refreshing-the-weekly-board).

### Brief and Map panels

| Panel | Endpoint | Dataset | Advanced by | Backfilled by |
|---|---|---|---|---|
| Grade cards — Detection / Magnitude / Timing | `/analysis/grade` | `analysis_grade_daily` | step 4 of the tick | `materialize_brief_grade --days N` |
| Grade history (trailing series) | `/analysis/grade-history` | `analysis_grade_daily` | step 4 of the tick | same |
| Standouts (vs each constraint's own history) | `/analysis/standouts` | `forecast_constraint_daily`, trailing 30d | step 2 of the tick | `backfill_forecast_history` |
| Hero trailing forecast comparison | `/analysis/hero` | `forecast_constraint_daily` | step 2 of the tick | same |
| Forecast μ profile, top constraints | `/analysis/forecast-mu`, `/analysis/top-constraints` | `forecast_sf_artifact` (decoded per request) | step 1 of the tick | `backfill_artifacts` |
| Map ranked constraints (constraint explorer) | `/map/constraints/ranked` | `forecast_sf_artifact` (decoded per request) | step 1 of the tick | `backfill_artifacts` |
| Node / top-node panels | `/analysis/node`, `/analysis/top-nodes` | `forecast_sf_artifact`, `forecast_nodal` | step 1 of the tick | `backfill_artifacts` |

Two things fall out of this table that are easy to get wrong:

* **`forecast_constraint_daily` is a *history* table, not the artifact's replacement.**
  Panels that show one day (the μ profile, ranked constraints) decode the artifact
  directly; panels that compare a day against its own trailing 30 days
  (standouts, hero) read the rollup. That is why re-cutting artifacts without
  re-running `backfill_forecast_history` leaves the comparisons stale while the
  single-day views already look correct.
* **The live per-day board is the only surface with no bulk repair path.**
  Every other panel can be regenerated over a date range; `scoreboard_daily` has to be
  walked one `--delivery-date` at a time, which is why its pre-change history is
  usually left to age out instead.

## What refits, and when

Nothing is fit once and frozen. Every delivery day gets a fresh fit on a rolling
trailing window.

| Object | Refit cadence | Window |
|---|---|---|
| μ heads (`p_bind`, `mu_gbm`) | **every delivery day**, inside `forecast_day` | trailing 240 days, `[D−240d, D)` |
| SF map (`map-v1`) | **weekly** — `ercot-map-refresh`, Sundays 18:00Z | trailing window, gated on freshness/coverage |
| Residual pool (bands) | fixed artifact | the backtest's OOS errors, strictly before D |

`DEFAULT_TRAIN_DAYS = 240` lives in `compute/mu_forecast/model/runner.py`. The SF map is
deliberately *not* refit per day: "the map fits this SF weekly, it is stationary
within the refit interval" (0095-0002), and the loader fails loud on a stale,
missing, or low-coverage map rather than silently serving one.

**Frozen is the configuration, not the parameters** — `train_days`, ridge λ,
`--features all`, arms, seed. The backtest span (2025-01-01 → 2026-07-15) is not a
training period whose coefficients got locked in; it is the *evaluation span* of a
walk-forward whose every fold refit on its own trailing 240 days. Its end date is
just when the walk was last run.

One consequence worth internalizing: because the window slides, **calendar time does
not grow the training set.** A fit in 2027 trains on exactly as many rows as one in
2025. More elapsed time buys more *evaluation* folds (power to detect whether a
change helped), new regimes passing through the window, and a deeper residual pool —
not a better-fed model.

## Jobs and scripts

| Job | Writes | Reads | Cadence |
|---|---|---|---|
| `compute.jobs.daily_forecast` | `forecast_nodal`, `forecast_sf_artifact`, `forecast_constraint_daily` | panel + weekly SF map | cron `ercot-forecast` 17:00Z (h1), `ercot-forecast-preview` 20:15Z (h2) |
| `compute.jobs.backfill_artifacts` | `forecast_sf_artifact`, `forecast_nodal` | refits per day (~8 min / 16 GiB) | manual |
| `compute.jobs.backfill_forecast_history` | `forecast_constraint_daily` | decodes existing artifacts only — never refits | manual, cheap |
| `compute.jobs.grade_day` | `scoreboard_daily` | `forecast_nodal` + realized DAM | folded into the daily tick; one day per run |
| `compute.jobs.materialize_brief_grade` | `analysis_grade_daily` | `forecast_sf_artifact` + settled DAM | manual / after settlement |
| `compute.jobs.load_scoreboard` | `scoreboard_weekly` | backtest CSVs under `runs/<run-id>/` | manual, only after a new backtest walk |
| `compute.jobs.weekly_map` | the SF map | trailing congestion panel | cron `ercot-map-refresh`, Sundays 18:00Z |

### What the two backfill jobs actually compute

These two are easy to conflate — one is hours of GPU-less number crunching, the
other is a decode.

**`backfill_artifacts` — recomputes the forecast itself.** It calls the *same*
`forecast_day` the live cron calls, one day per iteration, with the same arguments
(`backfill_artifacts.py:172-179`). For each delivery day D that means: build the
panel over `[D−240d, D+1)` at the correct vintage, **refit both μ heads** on the
trailing window, predict D's hours, then propagate through the weekly SF map to
per-node deterministic point forecast. It writes `forecast_nodal` rows and the
`forecast_sf_artifact` blob via `persist_forecast`. This is the ~8 min / ~16 GiB
per day, and it is why each day is causally honest: the fit for 2025-06-01 sees only
data ending 2025-06-01.

It also takes `--horizon`, which is not a label but a different forecast: the horizon
picks the day's historical **fire instant** (`_fire_time_for`, `backfill_artifacts.py:55-68`)
— 17:00Z on D−1 for h1, 20:15Z on D−2 for h2 — and that instant caps which covariate
vintages the fit may read. h1 and h2 are separate fits, and `horizon` is part of the
artifact's primary key.

**`backfill_forecast_history` — projects an existing artifact.** It refits nothing.
It loads one artifact on the exact `(run_id, delivery_date, horizon)` key, and reduces
its `E_mu` matrix (hours × constraints) down two numbers per constraint
(`forecast_history.py:16-21`):

```python
totals = values.sum(axis=0)        # forecast_mu:   the day's untruncated Σμ
hours  = values.ne(0.0).sum(axis=0)  # binding_hours: count of nonzero hours
```

Those land in `forecast_constraint_daily`, which is what makes constraint history
*queryable* — the artifact is a blob, so without this rollup the constraint-explorer
panel (`/map/constraints/ranked`) and the hero's trailing window would have to decode
every day on every request. It reads no realized prices and no neighboring days, so
it cannot introduce a leak: whatever vintage discipline the artifact has, the rollup
inherits.

The practical consequence: after any change to how artifacts are built, you must run
`backfill_artifacts` *and then* `backfill_forecast_history` over the same range.
Running only the first leaves the queryable history describing the old artifacts.

### Which jobs depend on the artifacts

Only the artifact-backed surfaces need rebuilding when the forecast artifacts change
(as in the 0133 CT-delivery-day re-cut). The dependency chain, in order:

```
backfill_artifacts        (per horizon — h1 and h2 are separate fits, not two labels
     |                     on one result; horizon is part of the artifact's PK)
     v
backfill_forecast_history (rollup; pure decode of the artifact above)
     v
materialize_brief_grade   (analysis_grade_daily)
```

```bash
# 1. artifacts — expensive, one fit per day
python -m compute.jobs.backfill_artifacts --run-id mu-all-v1 --map-run-id map-v1 \
    --horizon 1 --no-skip-existing --to-db --start 2026-08-01 --end 2026-08-14

# 2. rollup — cheap, decode-only
python -m compute.jobs.backfill_forecast_history --run-id mu-all-v1 --to-db \
    --horizon 1 --start 2026-08-01 --end 2026-08-14

# 3. grades — no cross-day state, so --days can span the whole range at once
python -m compute.jobs.materialize_brief_grade --run-id mu-all-v1 --horizon 1 \
    --delivery-date 2026-08-18 --days 600
```

`--no-skip-existing` is required only when overwriting artifacts that already exist
(a re-cut). When *extending* a track into days that have no artifact, leave it off —
the default skip-existing check is then exactly the resume semantics you want.

`scoreboard_weekly` and `scoreboard_daily` are **not** in this chain.
`load_scoreboard` re-transcribes the same CSVs unless the backtest walk itself is
re-run, and `grade_day` has no bulk date-range CLI — only `--delivery-date` one day
at a time.

## Gotchas

**Do not compare grades across surfaces.** A day can rank its constraints well
(#3 detection high) while the $/MWh magnitudes are poor (#2 `mae` bad), or the
reverse. Different currencies, different subjects.

**`persistence` is the reference that matters, not `null`.** Repeating yesterday
currently beats the model on all three Brief axes. `null` is a tripwire for a broken
metric path, not a meaningful bar to clear.

**Delivery days are 23, 24, or 25 hours.** Since 0133 the forecast block is cut on the
CT delivery day, so the fall-back day (e.g. 2025-11-02) has 25 hours and the
spring-forward day (e.g. 2026-03-08) has 23. Anything counting hours must allow the
full range — `forecast_constraint_daily`'s `binding_hours` check was originally
`BETWEEN 0 AND 24` and had to be widened to 25 (migration 45). Never build an hour
grid with `periods=24`.

**`scoreboard_weekly` is a transcription, not a measurement.** Re-running
`load_scoreboard` picks up nothing new from a forecast backfill. Its numbers only move
when the offline backtest walk is re-run.

**`scoreboard_daily` history is cron uptime, not an archive.** It grades one day per
tick and nothing bulk-refreshes it, so its window is however long the relevant cron
has been running — and after a change to the forecast, its older rows describe the
old behavior until they age out.

**One live board shows one horizon.** `/scoreboard/daily` serves a single track and
labels it; the final forecast is the default. Do not reintroduce an unfiltered query —
it silently interleaves final and preview grades for the same day.

**h2 exists only from the day the preview cron went live.** It is a serving-track
concept. There is no h2 history behind that date unless someone pays for 575 fits to
manufacture it.
