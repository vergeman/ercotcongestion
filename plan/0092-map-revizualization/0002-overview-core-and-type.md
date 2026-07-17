# 0002 - overview core + type (compute side)

Type: feat
Branch: feat/0092-0002-overview-core-and-type

> The compute-side build for the revizualized overview. The design of record is
> `0001-revizualization.md`; this doc carves out the server work it named so the
> web render (a later doc) has data to draw. Scope is **derivation + persistence +
> one read endpoint** — no render code here.

## Goal

* Give every located constraint two new honest, per-window scalars so the overview
  can de-pile it and pick its mark:
  * **`|SF|²` core** (`core_lat`, `core_lon`) — the intensity-weighted **geometric
    median** (Weiszfeld), which snaps onto the dominant lobe instead of averaging to
    the empty center the way the existing `|SF|`-mean centroid does (50% within
    100 km of state center → 15%; see `spike/core_spike.py`).
  * **type** (`gtc` / `transmission` / `radial`) — from the contingency string and
    the already-persisted rail signature. Cheap, no new fit.
* Serve them, plus each constraint's signed top-K node field, from **one bulk
  endpoint** `/map/overview` so the client renders the whole overview from a single
  indexed slice per window.

## Context

* The core and type derive from the **same per-window honest SF** as everything
  else on the map — never a global fit. They are new *summaries* of an existing fit,
  so they belong in `constraint_geography`'s output and `constraint_geo`'s row,
  written by the existing geo-persist path.
* `constraint_geo` already carries `lat/lon` (the `|SF|`-mean centroid — keep it,
  it is still the marker for the flat `/map/constraints` layer), `max_abs_sf`,
  `binding_hours`, `n_rail`, `peak_offrail`, `spread_km`, `zone_shares`. The core
  and type are two more columns on the same key `(run_id, window_start,
  constraint_key)`.
* The geometric median needs a constraint's **full** `|SF|` vector (all its nodes),
  not the top-K — computing it at request time would re-read every node for N
  constraints. Persist it in the fit path (where the full SF matrix is already in
  hand) and the endpoint stays a plain read, exactly like the other `constraint_geo`
  columns.
* Type rule (validated in `spike/type_sign_probe.py`, matches
  `docs/ERCOT_constraints.md` §4 shape logic):
  * **gtc** ← contingency component of `constraint_key` is `BASE CASE` (interface /
    generic transmission constraint; large regional footprint).
  * **radial** ← `n_rail >= 1 AND peak_offrail < 0.25` (a rail with little graded
    body beneath it — a pocket/resource, one point).
  * **transmission** ← everything else (a real line + real contingency; co-located,
    a corridor reads right).
  * Counts on the live window: gtc 87, transmission 952, radial 5.

## Approach

* **`compute/mu/geo.py`**
  * `constraint_core(SF, sp) -> DataFrame[core_lat, core_lon]` — Weiszfeld geometric
    median of each constraint's located nodes weighted by **`|SF|²`**. Mirror
    `constraint_geography`'s contract exactly: intersect `SF.columns` with `sp.index`,
    weights from `SF[known].abs()**2`, all-zero / no-known-coord rows → **NaN, not a
    fallback** (holes stay holes). Seed Weiszfeld at the `|SF|²`-weighted mean, iterate
    to a fixed tol / max-iter, guard the zero-distance singularity. Reuse
    `haversine_km`. Vectorize across constraints where practical; a per-row loop is
    acceptable (N ≈ 1k, fast).
  * `constraint_type(geo) -> Series` — pure classifier over already-derived per-row
    fields (`constraint_key` contingency, `n_rail`, `peak_offrail`). Returns the
    `{"gtc","transmission","radial"}` enum. No coordinates needed.
  * Wire both into the frame `constraint_geography` (or its caller in the geo-persist
    path) already builds per window, as `geo_core_lat`/`geo_core_lon`/`geo_type`.
    **Do NOT touch `fit.py`, `refit_grid`, or the walk-forward derivation.**
* **`db/migrations/30_constraint_geo_core.sql`** — `ALTER TABLE constraint_geo ADD
  COLUMN core_lat REAL, core_lon REAL, ctype TEXT`. Nullable (backfilled after the
  fit; NULL for older runs, like `sf_stability`).
* **`compute/sf/geo_persist.py` + `compute/sf/persist.py`** (`copy_constraint_geo_rows`)
  — carry the three new columns through the COPY so a normal map refit populates them.
* **`api/map.py` + `api/models.py`** — `GET /map/overview`:
  * params `n` (top constraints by `binding_hours`, default ~70), `k` (top nodes each,
    default ~16), `min_frac` (peak-relative node floor, reuse the `/map/reach` idea).
  * resolve the served window (`_resolve`/`_meta_row`), read the top-N
    `constraint_geo` rows, then each constraint's top-K signed nodes from
    `implied_shift_factors` (one indexed query per constraint, as `/map/reach` does).
  * response `MapOverview{ run_id, window_start, window_end, oos_r2, sf_stability,
    n, k, constraints: [OverviewConstraint] }`, where `OverviewConstraint{
    constraint_key, ctype, binding_hours, max_abs_sf, core_lat, core_lon, lat, lon,
    nodes: [OverviewNode{settlement_point, sf, lat, lon}] }`. Signed `sf` on the
    nodes is what the drill-down colors; the overview render ignores the sign.
* **`web/`** — out of scope for this doc; types + render land with the render doc.

## Acceptance

* [ ] `constraint_core` returns the `|SF|²` geometric median; a constraint whose mass
  is all on uncoordinated nodes → NaN (parity with `constraint_geography`). A unit
  case with two lobes lands the core **on the heavier lobe**, not between them.
* [ ] `constraint_type` labels the live window gtc 87 / transmission 952 / radial 5
  (matches `spike/type_sign_probe.py`).
* [ ] A map refit persists `core_lat`, `core_lon`, `ctype` on `constraint_geo`;
  migration applies clean; older runs read NULL without error.
* [ ] `GET /map/overview?n=70&k=16` returns each constraint at its core with its
  type and its top-K signed nodes; unlocated constraints carry NULL core.
* [ ] Positioning stays walk-forward-honest (per-window SF only); `pytest` green.
