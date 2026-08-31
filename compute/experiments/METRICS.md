# Baselines & metrics — one map

The words `oracle`, `persistence`, `climatology` reappear at every layer and mean
something slightly different each time. This pins them down.

## The pipeline

```
forecast (μ)  ──►  SF map  ──►  nodal congestion  ──►  graded
```

Each test freezes everything except one layer and swaps baselines in to bracket
that layer's skill.

## The four arenas

| Arena                  | Code                                     | What moves (rest frozen)            | Baselines                                            | Metrics                                                    |
|------------------------|------------------------------------------|-------------------------------------|------------------------------------------------------|------------------------------------------------------------|
| **SF gate**            | `sf_out_of_window/`, `evaluation/sf.py`  | the SF map (forecast fed the truth) | oracle, persistence, climatology, null — as μ inputs | pooled R², rank-Spearman, sign-agree (±$1), top-decile hit |
| **μ gate**             | `evaluation/mu.py`, `experiments/mu/`    | the μ forecast (map fixed)          | same four **+ `model`** (the real forecast)          | same four                                                  |
| **Forecast internals** | `mu_forecast/model/heads.py`             | the two heads themselves            | head-2's own climatology                             | bind reliability (head 1), R² (head 2)                     |
| **Production grade**   | `analysis/grade.py`, `jobs/grade_day.py` | the shipped forecast, live          | persistence, optional climatology (no oracle)        | detection, magnitude, timing                               |

## Where the UI reads from

- **/scoreboard** — the **μ gate**. Just reshapes `mu_score_weekly.csv`
  (`load_scoreboard.py`): the gate metrics (rank-Spearman, sign-agree,
  top-decile) across all five sources, oracle included. Offline, weekly.
- **/brief "Forecast Grade"** — the **production grade** (`brief_grade.py` →
  `grade_profiles`): detection / magnitude / timing, vs persistence and
  climatology only. Live, per delivery day, no oracle.

Same forecast underneath — different yardsticks for different audiences
(offline model-selection vs the live public grade). "persistence" and
"climatology" appear in both but are scored differently in each.

## What the names mean

- **oracle** — the cheating upper bound. Fed the actual realized μ, so it
  measures the ceiling nothing can beat. Perfect μ *per constraint*, but still
  the fitted `SF[node, constraint]` — so with the forecast pinned to the answer,
  the only thing left to vary is the map, and oracle measures the map's quality.
  (SF gate: the map's best case. μ gate: the forecast's best case. Not in
  production — you never know the answer in advance there.)
- **persistence** — "tomorrow = today": repeat yesterday's same-hour realized
  value. Dumb but surprisingly strong, because congestion clusters — recent
  binding tells you which constraints are currently live.
- **climatology** — the "typical for this time" guess: `P(bind | hour) × mean μ
  when binding` — a historical-average μ per constraint. (Exact form varies by
  layer — see below.)
- **null** — predict nothing (zeros); the know-nothing floor.
- **model** — the real forecast: `P(bind) × E[μ | bind]`, the two heads multiplied.

## climatology means three different things

- **μ gate** (`evaluation/mu.py`): `P(bind | hour) × average μ when binding`.
  Stands alone, so it carries its own P(bind).
- **Head 2** (`heads.py`): average μ by (load level × hour), binding hours only.
  No P(bind) — it's the severity backbone the model has to beat.
- **Production** (`grade.py`): last window's pattern, compared on live data.

## Metrics in plain terms

**Gate metrics** (SF gate, μ gate):
- **pooled R²** — a dollar-magnitude measure of how close the predicted
  congestion values are. *Pooled* = one score over all nodes and hours lumped
  together. *R²* = how much of the variation the model explains: 1 = perfect,
  0 = no better than guessing the average, negative = worse than that.
- **rank-Spearman** — did it order the nodes worst-to-best correctly.
- **sign-agree** — did it get the direction right (±$1 counts as zero — see
  deadband).
- **top-decile hit** — of the truly worst 10% of nodes, how many it flagged.

**Production metrics** (`grade.py`):
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
