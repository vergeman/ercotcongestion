# Baselines & metrics by arena

The words `oracle`, `persistence`, `climatology` reappear at every layer and mean
something slightly different each time. This pins them down.

## The pipeline

```
forecast (μ)  ──►  SF map  ──►  nodal congestion  ──►  graded
```

Each test freezes everything except one layer and swaps baselines in to bracket
that layer's skill.

## The five arenas

| Arena                  | Code                                     | What moves (rest frozen)            | Baselines                                            | Metrics                                                    |
|------------------------|------------------------------------------|-------------------------------------|------------------------------------------------------|------------------------------------------------------------|
| **SF gate**            | `sf_out_of_window/`, `evaluation/sf.py`  | the SF map (forecast fed the truth) | oracle, persistence, climatology, null — as μ inputs | pooled R², rank-Spearman, sign-agree (±$1), top-decile hit |
| **μ gate**             | `evaluation/mu.py`, `experiments/mu/`    | the μ forecast (map fixed)          | same four **+ `model`** (the real forecast)          | same four                                                  |
| **Forecast internals** | `mu_forecast/model/heads.py`             | the two heads themselves            | head-2's own climatology                             | bind reliability (head 1), R² (head 2)                     |
| **Scoreboard grade**   | `jobs/grade_forecast_day.py`             | the served nodal forecast, live     | oracle, persistence, climatology, null               | rank-Spearman, sign-agree, top-decile hit; model ESSP      |
| **Brief grade**        | `analysis/brief_grade.py`, `jobs/materialize_brief_grade.py` | the served Brief artifacts, live | persistence, optional climatology                    | detection, magnitude, timing                               |

## Where the UI reads from

- **`GET /scoreboard/summary`** — combines two nodal scorecard tracks: 1. the
  offline, one-time weekly μ evaluation loaded by `jobs/backfill_scoreboard.py`,
  and 2. the daily forecast rows written by `jobs/grade_forecast_day.py`. Both
  use the three screening metrics; only the model's live row also carries ESSP
  precision/recall.
- **`/brief` "Forecast Grade"** — reads the Brief-grade track materialized by
  `jobs/materialize_brief_grade.py` from `analysis/brief_grade.py`: detection,
  magnitude, and timing versus persistence and climatology. It is not a
  Scoreboard metric.

The same forecast feeds all three consumers, but internal gates, Scoreboard,
and Brief use different subjects and currencies. "persistence" and
"climatology" therefore have to be interpreted within their own arena.

## What the names mean

- **oracle**: the cheating upper bound. Fed the actual realized μ, so it
  measures the ceiling nothing can beat. Perfect μ *per constraint*, but still
  the fitted `SF[node, constraint]` - so with the forecast pinned to the answer,
  the only thing left to vary is the map, and oracle measures the map's quality.
  (SF gate: the map's best case. μ gate: the forecast's best case. The live
  Scoreboard computes it only after settlement as a ceiling, never as a
  deployable forecast.)
- **persistence**: "tomorrow = today": repeat yesterday's same-hour realized
  value. Dumb but surprisingly strong, because congestion clusters: recent
  binding tells you which constraints are currently live.
- **climatology**: the "typical for this time" guess: `P(bind | hour) × mean μ
  when binding`: a historical-average μ per constraint. (Exact form varies by
  layer: see below.)
- **null**: predict nothing (zeros); the know-nothing floor.
- **model**: the real forecast: `P(bind) × E[μ | bind]`, the two heads multiplied.

## Climatology is arena-specific

- **μ gate** (`evaluation/mu.py`): `P(bind | hour) × average μ when binding`.
  Stands alone, so it carries its own P(bind).
- **Head 2** (`heads.py`): average μ by (load level × hour), binding hours only.
  No P(bind) — it's the severity backbone the model has to beat.
- **Scoreboard grade** (`jobs/grade_forecast_day.py`): a trailing-window μ
  baseline, projected through the same map and scored on settled nodal
  congestion.
- **Brief grade** (`analysis/brief_grade.py`): optional profile comparator for
  the settled Brief subjects.

## Metrics in plain terms

**Internal gate metrics** (SF gate, μ gate):
- **pooled R²** — a dollar-magnitude measure of how close the predicted
  congestion values are. *Pooled* = one score over all nodes and hours lumped
  together. *R²* = how much of the variation the model explains: 1 = perfect,
  0 = no better than guessing the average, negative = worse than that.
- **rank-Spearman** — did it order the nodes worst-to-best correctly.
- **sign-agree** — did it get the direction right (±$1 counts as zero — see
  deadband).
- **top-decile hit** — of the truly worst 10% of nodes, how many it flagged.

**Scoreboard metrics** (`jobs/grade_forecast_day.py`): rank-Spearman,
sign-agreement, and top-decile hit on settled nodal congestion. The model row
also records ESSP precision/recall when a served SF artifact is available.

**Brief-grade metrics** (`analysis/brief_grade.py`):
- **detection** — did it catch the hours that actually congested.
- **magnitude** — how much of the real congestion its forecast overlapped.
- **timing** — detection skill above chance, by day and by hour.

## Other terms

- **OOS** — "out-of-sample" (here, out-of-window: the test set). Score the model
  on data it did *not* train on. Training on a window that overlaps the test week
  inflates the score (0.986); testing on a strictly-later week gives the real
  number (0.746).
- **deadband** — a "close enough to zero, ignore it" band. A $1/MWh deadband
  means: if a price is within ±$1, treat it as no congestion, so tiny meaningless
  wiggles don't count as a right-or-wrong sign call.

## Note

The four gate metrics live in three copies (`metrics.py`, `evaluation/sf.py`,
`sf_out_of_window/common.py`) on purpose — each test defines its own so it can't
silently drift when another changes.
