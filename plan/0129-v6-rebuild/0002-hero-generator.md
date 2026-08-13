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
* Known constraints: `cast` carries only 32 of 281 settled keys (serving floor); `constraint_geo.zone_shares` is stamped 2025-12-13; ESSP (`0008`) is not built, so node dedupe is coordinate-based; load series carry `basis=forecast` with no actual.

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
* `magnitude` MUST carry `basis` and `n_keys`. Rank the forecast against a distribution restricted to the **same cast keys**; carry the all-keys total as separate context. Comparing a floor-truncated forecast (32 keys) against a full settled total (281) prints "badly under-called" every day for a structural reason.
* `where`: zone shares Σμ-weighted from `constraint_geo`, plus node-side zone from the geocoded layer. Stamp `geo_as_of` on the constraint half.
* `exceptions`: count tier-0 (never bound in window) and tier-1 (top-3 of own window) above the materiality gate. Dedupe nodes by coordinate and record `"dedupe":"coordinate"` — this over-counts until `0008` lands.
* Mark slots that cannot be reconciled (`"reconcilable": false`) — load has no actual side.
* Grade each slot independently. Do NOT blend slots into one score; signed errors net out and print "balanced" while both halves are wrong (see `0003`).

**Phrase book** — `compute/analysis/phrases.py`

* One ordered ladder per slot: `(predicate, bucket, template)` tuples, read top to bottom in a single file.
* Every ladder's final rung is unconditional, and every ladder has a boring rung — on 2026-07-28 the forecast hero lands on `ordinary`, and that is the correct output.
* Bucket names are stable identifiers; templates are the only thing that changes when reworking voice.
* `verdict` is rung-distance on the magnitude enum — `ordinary` → `near_top` is two rungs up → `under_called`. No new thresholds.
* Render to segments, never a flat string: `[{"text": "...", "ref": "magnitude"}, ...]` so the frontend attaches tooltips and jump targets by `ref` without parsing prose.
* Carry `cursor: {ws, we, t}` on the response — the delivery day's CT bounds plus the hour worth opening on. `t` is a judgment (peak congestion hour), so it belongs here rather than being re-derived in the frontend; `0010` hands it straight to the Map deep link.
* Phrase surprises as "constraints the forecast doesn't carry", not "the forecast missed" — on 2026-07-28 all 14 were outside the cast, so the count measures the serving floor.

**Serving** — `api/analysis.py`

* New `GET /analysis/hero`, resolving `run_id` off `forecast_current` and coalescing horizon exactly as `get_brief` does.
* The endpoint's `?date=` is an **API request parameter and has nothing to do with the retired page-URL `?date`** (`0009`). The page speaks the time cursor and derives a CT day to call the API with; the API speaks delivery days. Do not "harmonise" these — they are different layers.
* Response: `{segments: {headline, lede}, slots: {...}, verdict: {...}|null, provenance: {...}}`.
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

* [ ] `GET /analysis/hero?date=2026-07-28` returns segments, slots and provenance in one response; no prose is assembled in the frontend.
* [ ] Forecast basis for 2026-07-28 yields `magnitude {value 11892, rank 9 of 31, ratio 1.17, basis "cast_keys", n_keys 32, bucket "ordinary"}` and `regime {load.system, pct 100 of 361, bucket "load_record_high", reconcilable false}`.
* [ ] Settled basis for the same day yields `magnitude {value 23044, rank 2, ratio 2.26}` on the cast keys, `all_keys {value 36679, rank 1}`, and `verdict {bucket "under_called", rungs 2}`.
* [ ] `where` reports south 0.546 forecast / 0.543 settled with `geo_as_of "2025-12-13"`, and its verdict is `held`.
* [ ] Every hero segment carries a `ref` resolving to a slot key; every slot carries the raw numbers behind its adjective.
* [ ] Unit test: a table of synthetic slot inputs → expected bucket, per ladder, with no DB.
* [ ] Exhaustiveness test: every bucket in every ladder has a template, and every ladder's last rung is unconditional.
* [ ] Golden test: 365 days rendered to a checked-in text file; no bucket accounts for more than half the days in any ladder.
* [ ] Window queries filter `WHERE ts < D`; a test pins that a backfilled day does not see data published after it.
* [ ] Re-running the endpoint for a past day reproduces byte-identical segments.
