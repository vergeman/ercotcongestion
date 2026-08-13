# 0129-0002 - hero-generator

Type: feat
Branch: feat/0129-0002-hero-generator
Depends on: `0001` (the regime slot reads the condition series `0001` repairs)

## Goal

* Add a deterministic hero generator: trailing-window queries → classified slots → rendered headline/lede text, all server-side.
* Serve it at `GET /analysis/hero` as text segments plus the supporting slot values, on a forecast or DAM-settled basis.
* Emit a `verdict` per slot once DAM has landed, so the page grades its own morning claim without a second text block.
* Ship a 365-day golden file of generated headlines as the review artifact for vocabulary changes.

## Context

* v6's hero (`docs/daily_brief_v6_prototype.html:1718 renderHead`) restates the top table row from `D.regimes[0]` — an axis/spread caption with no sense of whether the day is unusual. `D.regimes` is prototype-only and exists nowhere in `compute/` or `api/`.
* The desired register is v5's (`docs/daily_brief_v5_prototype_hero.html:433 renderLead`) — "a near-record day… three things stand apart" — but its place names ("deep South Texas", "the Valley and Duval County") were hand-typed. On 2026-07-28 the node extremes actually split 8 North / 6 South, so that claim was wrong as well as underivable.
* Everything the hero needs is already-persisted and timestamp-keyed: `ercot_dam_shadow_prices` (hypertable on `interval_ts`), the SPP/λ congestion panel, the tracked condition series, and `forecast_sf_artifact`. Nothing requires the model fit, so this is a query, not a cron step.
* `docs/daily_brief_page*.md` and `docs/daily_brief_engine*.md` are outdated — v6 is the current outline. The prototype payload shapes (`const D`, `const X`) are not a contract.
* Known constraints: the legacy brief's `cast` carries only 32 of 281 settled
  keys (a serving-floor screen, not artifact metadata); `constraint_geo.zone_shares`
  is stamped 2025-12-13; ESSP (`0008`) is not built, so node dedupe is
  coordinate-based; load series carry `basis=forecast` with no actual.

## Approach

* Work in: `compute/analysis/`, `api/analysis.py`, `tests/`
* Entry point / primary change: `compute.analysis.hero.build_hero(conn, run_id, D, horizon, basis)` → slot dict; `compute.analysis.phrases.render(slots)` → segments.

**Window queries** — `compute/analysis/hero_window.py`

* One aggregate query per source, `GROUP BY` the delivery day in America/Chicago (HE = local hour + 1). Push the reduction into Postgres.
* Do NOT reuse `compute/sf/panels.py::load_shadow_prices` / `load_congestion_panel` — they pivot to full hourly panels (~720h × ~3,000 keys over 30 days) to produce 30 daily sums per key.
* Every window filters `WHERE ts < D`. The hero must be reproducible as-of the delivery day, never as-of now — same walk-forward discipline as the geo panel's window guard.
* Returns: per-constraint daily Σμ series + `rank`/`days_bound`/`med`/`prior_last`; per-node daily mean congestion series + `rank`; condition series `today`/`median`/`pct`/`n`/`basis`.

**Classifiers** — `compute/analysis/hero.py`

* Four slots: `magnitude`, `regime`, `where`, `exceptions`. Pure functions over the window dict — no I/O, no DB.
* `magnitude` MUST carry `basis` and `n_keys`. Its primary universe is the full
  **artifact-key** vocabulary: the constraints the day's SF+μ artifact actually
  models. Rank forecast and settled totals against trailing distributions over
  those same keys. Carry the all-DAM-keys total as separate context, including
  the keys outside the model vocabulary. Comparing unlike universes prints
  "badly under-called" every day for a structural reason.

  Do **not** recreate the legacy brief's 32-key serving cast here. That screen
  was a precomputed-payload presentation choice, not metadata persisted on
  `forecast_sf_artifact`; inferring it from non-zero μ would silently discard
  low-but-real model possibilities. The rebuild is query-first, so the hero
  reports the complete model vocabulary and leaves request-side below-floor
  filtering to `0005`'s panel consumers.

  Its middle ladder is data-bearing rather than a synonym pool: `ordinary_low`
  is 50–75% of the trailing median, `ordinary` is 75–110%, and `ordinary_high`
  is 110–125%; `quiet` remains ≤50% and `elevated` begins at 125%. The reviewed
  year populated those bands 70 / 109 / 35 times, respectively.
* `where`: zone shares Σμ-weighted from `constraint_geo`, plus node-side zone from the geocoded layer. Stamp `geo_as_of` on the constraint half. Its ladder is
  `distributed` below 45%, `tilted` at 45–55%, and `concentrated` at 55% or
  higher; this avoids presenting a 49%/51% leader flip as a qualitative change.
* `exceptions` is a **settled constraint-window** slot; it does not require SF.
  Its candidate set is DAM constraints outside the artifact-key vocabulary, so
  the prose describes a coverage fact rather than blaming a low forecast.
  * tier-0: the constraint has a non-zero daily DAM Σμ today and no non-zero
    daily DAM Σμ on the prior 30 delivery days;
  * tier-1: the constraint has a non-zero daily DAM Σμ today and its value ranks
    in the top three of its own 31-day daily Σμ series (ties use the conservative
    last-tied rank).

  Return counts and raw candidate values/ranks. There is no dollar materiality
  gate and no node/coordinate dedupe in the hero: `$50` appears only in the
  prototype mock, not in an established backend contract, and node materiality
  belongs to the later Standouts work unblocked by `0003`. Before DAM lands,
  mark this slot unavailable rather than emitting a zero count.
* Mark slots that cannot be reconciled (`"reconcilable": false`) — load has no actual side.
* Grade each slot independently. Do NOT blend slots into one score; signed errors net out and print "balanced" while both halves are wrong (see `0003`).

**Phrase book** — `compute/analysis/phrases.py`

* One ordered ladder per slot: `(predicate, bucket, template)` tuples, read top to bottom in a single file.
* Every ladder's final rung is unconditional, and every ladder has a boring rung — on 2026-07-28 the forecast hero lands on `ordinary`, and that is the correct output.
* Bucket names are stable identifiers; templates are the only thing that changes when reworking voice.
* `verdict` is rung-distance on the magnitude enum — `ordinary` → `near_top` is two rungs up → `under_called`. No new thresholds.
* Render to segments, never a flat string: `[{"text": "...", "ref": "magnitude"}, ...]` so the frontend attaches tooltips and jump targets by `ref` without parsing prose.
* Carry `cursor: {ws, we, t}` on the response — the delivery day's CT bounds plus the hour worth opening on. `t` is a judgment (peak congestion hour), so it belongs here rather than being re-derived in the frontend; `0010` hands it straight to the Map deep link.
* Phrase surprises as "constraints outside the model vocabulary", not "the
  forecast missed". A low forecast value is a model opinion; absence from the
  artifact-key vocabulary is the distinct coverage fact the phrase describes.

**Vocabulary review diagnostics** — `compute/jobs/render_hero_golden.py`

* Every audit row carries compact raw diagnostics beside its bucket names:
  magnitude rank/31-day ratio, regime percentile, leading-zone share, and
  tier-0/tier-1/counts for exceptions. The fixture is the decision surface for
  refining rungs; do not add synonym rotation that conceals unchanged evidence.
* Production review over 2025-07-29–2026-07-28 found materially different
  whole-DAM hourly medians by CT hour: 08:00–09:00 are about $328 while
  15:00–18:00 are $1,030–$1,165. A later refinement may compare a data-declared
  high-congestion slice (initial candidate HE16–HE19) against its own trailing
  slice history, alongside—not instead of—the whole-day slot. Choose and validate the
  boundary from the diagnostic audit and day-level rank changes before adding a
  peak/off-peak bucket or phrase. The first implementation ships the selected
  HE16–HE19 comparison as nested magnitude evidence (`high_congestion_hours
  {value, rank, ratio, hours_ct}`), including in the audit, but does not yet
  alter the primary headline rung. When it differs from whole-day magnitude by
  two or more coarse magnitude bands, a deterministic subordinate headline
  clause says so; fine-rung verdict distance remains intact while one-band
  differences remain diagnostic-only. This is an empirical
  high-congestion slice, not ERCOT's
  contractual on-peak period; reserve `peak` / `on_peak` terminology for a
  market-calendar-aware implementation.
* The hero's exceptions phrase is count-bearing. For a non-empty settled slot it
  names the number of constraints outside the artifact vocabulary and, when
  applicable, how many are newly active (tier-0), rather than flattening every
  day to “several.”

**Serving** — `api/analysis.py`

* New `GET /analysis/hero`, resolving `run_id` off `forecast_current` and coalescing horizon exactly as `get_brief` does.
* The endpoint's `?date=` is an **API request parameter and has nothing to do with the retired page-URL `?date`** (`0009`). The page speaks the time cursor and derives a CT day to call the API with; the API speaks delivery days. Do not "harmonise" these — they are different layers.
* Response: `{segments: {headline, lede}, slots: {...}, verdict: {...}|null, provenance: {...}}`.
  Declare this as a FastAPI/Pydantic `available`-tagged available-or-soft-fail response
  contract in `api/models.py`; the slots retain extensible raw evidence while
  the envelope, segments, cursor, and provenance are schema-validated.
* One phase, selected by data: settled slots when DAM has landed for the day, forecast slots otherwise. Same sentence shape and same lede length in both — a verdict chip and one subordinate clause are the only visual difference.
* Add a small TTL/LRU keyed `(run_id, delivery_date, horizon)` if cold latency warrants it; the hero is identical for every viewer of a day.

**Geography (last, hero ships without it)** — `preprocess/`

* `data/raw/TIGER/` and the zone shapefiles are excluded from the image by `.dockerignore`; `data/processed/` is copied in (Dockerfile:54). Geography does not change, so the join is build-time.
* New preprocess script emitting `settlement_point,county,weather_zone` (~1,106 rows) into `data/processed/`, reusing `preprocess/assign_bus_weather_load_zones.py::assign_zone`.
* Until then `where` uses the `load_zone` column already present in `data/processed/settlement_points_geocoded.csv` — no new plumbing.

**Out of scope**

* Do NOT touch: `analysis_brief`, `compute/analysis/assemble.py::build_brief`, `compute/jobs/daily_brief.py`, `_brief_latest`, or the cronjobs. No persistence, no backfill.
* Do NOT build `day.regimes` / `day.hub_board` / `day.grade` — the hero removes `regimes` from the critical path.
* Do NOT emit any place name that is not a join result, and do not read `web/src/components/map/GridMap.tsx:108 CITY_LABELS` (hand-typed, display-only).

## Acceptance

* [x] `GET /analysis/hero?date=2026-07-28` returns segments, slots and provenance in one response; no prose is assembled in the frontend.
* [x] The endpoint declares a Pydantic available-or-soft-fail response model;
  OpenAPI exposes both shapes and validates the stable envelope.
* [x] Forecast basis for 2026-07-28 yields an `artifact_keys` magnitude slot:
  the complete `forecast_sf_artifact` vocabulary, its trailing-30-day rank and
  ratio, and an `ordinary` bucket. It does not infer or report a legacy
  32-key cast.
* [x] Settled basis for the same day uses that exact same artifact-key universe,
  carries `all_keys {value 36679, rank 1}` for the full DAM vocabulary, and
  emits a magnitude verdict from the two existing bucket positions. The
  response makes both universes and their `n_keys` explicit.
* [x] Settled exceptions report only DAM constraints outside the artifact-key
  vocabulary. Each tier carries the raw daily Σμ and its trailing-window rank;
  a forecast-phase response marks the slot unavailable rather than reporting
  zero exceptions.
* [x] `where` reports south 0.489 forecast / 0.545 settled with
  `geo_as_of "2025-12-13"`, and its zone verdict is `held`. The forecast is
  tilted toward south in both phases; this supersedes the prototype's stale
  0.546/0.543 values after the full artifact vocabulary replaced its cast.
* [x] Every hero segment carries a `ref` resolving to a slot key; every slot
  carries the raw numbers behind its adjective.
* [x] Unit test: a table of synthetic slot inputs → expected bucket, per ladder,
  with no DB. An exhaustiveness test verifies every bucket has a template and
  each ladder's final rung is unconditional.
* [x] Historical window reads use an explicit delivery-day cutoff, never
  `now()`. A test pins the generated SQL's strict end bound, so the endpoint
  does not widen a past-day window as time passes.
* [x] Re-running the endpoint for an unchanged past-day data set reproduces
  byte-identical segments.
* [x] A manually invoked audit renderer produces a checked-in 365-day text file
  of the generated hero segments and buckets. It is a browsable mass-review
  artifact, never API output or database state; generation is read-only and is
  not scheduled as a cron or backfill job. The audit fails if an available slot
  bucket accounts for more than half of the reviewed days. The checked-in
  complete-year review snapshot may deliberately use the renderer's explicit
  `--allow-dominant` override: ordinary magnitude/regime outcomes naturally
  dominate a full calendar year. That invocation writes an `audit_mode` header
  into the fixture so it is reviewable in git; it is a vocabulary-review choice,
  not a passing strict audit or an API behavior.
* [x] No hero text, slot, or rollup is persisted. The endpoint queries its
  inputs and renders every response on demand.
