# Spec — Phase 1: serve the map (SF exposures, geography, node explorer)

**Context:** `serving-and-display-design.md` Phase 1. Serve the asset that already
works — the implied shift-factor map (oracle **0.787**) — with **no forecast involved**.
Node explorer (click a node → what drives it) and constraint overlay (where constraints
live, from the |SF|-weighted centroid), from a current SF fit on realized data. The node
values on the map stay **congestion** (realized SPP − system_λ, already served by Phase 0);
Phase 1 adds the SF *structure* — which constraints drive which nodes, and where those
constraints live — on top of it.

---

## 0. The finding that shrinks this phase: SF persistence already exists

The SF matrix is already persistable to Postgres — the tables were built for exactly
this (migration `25_implied_shift_factors.sql` even names "node explorer" as the
consumer). The API simply doesn't **read** them yet.

- **`implied_shift_factors(run_id, window_start, constraint_key, settlement_point, sf)`**
  — the signed SF matrix per refit window, threshold-sparsified, PK
  `(run_id, window_start, constraint_key, settlement_point)`, indexed on
  `(run_id, window_start)`.
- **`sf_window_meta(run_id, window_start, window_end, score_start, score_end, n_kept,
  n_dropped, n_sf_clipped, fit_r2, oos_r2, coverage)`** — one row per refit boundary.
- **`compute.sf.runner --persist`** fits `C ≈ −M·SFᵀ` on the rolling window and writes both
  tables; `compute/sf/persist.py` has the `COPY`/upsert helpers. (Phase 1 uses only
  `--persist` — the SF matrix and window meta. It does **not** touch the legacy
  binding-proximity panel or its pointer.)

So Phase 1's compute is mostly **"run the existing SF runner on a fresh, non-legacy
run_id + add constraint geography"**; the serving is the genuinely new part.

---

## 1. Compute — the map run

### 1.1 Fit + persist the SF map (existing runner)
Run `compute.sf.runner` over the full history through the latest legal window with
`--persist` under a fresh run_id (e.g. `map-v1`), at the adopted operating
point (window 240d, refit 7d, λ=1, min_binding_hours=25, standardize). One run populates
**every** refit window in `implied_shift_factors` + `sf_window_meta` — so the *current*
window serves the explorer now, and the *historic* windows are already in place for the
Phase-4 slider. No new fitting code.

### 1.2 Constraint geography (the one new persistence)
`compute/mu/geo.py::constraint_geography(SF, sp)` maps each constraint key to its
|SF|-weighted centroid + zone/kV, from `load_sp_geography` (the geocoded SPs). Apply it to
**each persisted window's** SF and write a new table (§2). Columns available directly from
`geo.py`: `geo_lat`, `geo_lon`, `geo_spread_km` (multimodality caution — a bimodal
constraint's centroid can land between its two lobes), `geo_kv_mean/max`, `geo_zone_<z>`
mass shares. Add `max_abs_sf = max_sp |SF|` (the constraint's peak exposure magnitude — the
*stable* summary, §6) and `binding_hours` (support) per constraint from the same window.

Leak-safety is inherited: `geo.py` fits SF on the honest trailing window itself and
**refuses a global SF** (`geo_panel` never accepts a pre-fit SF) — so per-window geo is
walk-forward-honest by construction (the fitted-SF leak trap, memory
[[sf-map-as-geographic-crosswalk]]).

### 1.3 Stability (fit confidence for the explorer)
`compute/sf/eval.py::_sf_corr` gives disjoint-adjacent-window SF correlation. Persist a
**window-level `sf_stability`** onto `sf_window_meta` (new nullable column) from
consecutive refits. Per-*constraint* stability is harder (needs matched keys across
windows) — defer it; the window-level number + `oos_r2`/`coverage` already let the
explorer label a refit's trustworthiness. This matters because identifiability is
unsolved (§6).

---

## 2. DB — one new table

Existing tables (§0) are reused as-is. Add:

```sql
CREATE TABLE constraint_geo (
    run_id         text        NOT NULL,
    window_start   timestamptz NOT NULL,
    constraint_key text        NOT NULL,
    lat  real, lon real,
    spread_km      real,       -- multimodality caution flag when large
    kv_mean real, kv_max real,
    zone_shares    jsonb,      -- {load_zone: |SF|-mass share}
    max_abs_sf     real,       -- max_sp |SF|  (peak exposure magnitude; the stable summary)
    binding_hours  int,        -- support in the fit window
    PRIMARY KEY (run_id, window_start, constraint_key)
);
-- new nullable column on the existing table:
ALTER TABLE sf_window_meta ADD COLUMN sf_stability real;
```
No `forecast_*` tables here — those are Phase 2.

---

## 3. API — the `/map/*` endpoints

**Run + window resolution (no legacy pointer).** The served map run is named by config —
`settings.map_run_id` (defaults to the newest run_id in `sf_window_meta`); sweep run_ids
are ignored. The **current refit** = the max `window_start` for that run in
`sf_window_meta`, resolved per request so a re-persist of the same run_id is picked up
without redeploy. No `implied_binding_proximity_current` pointer, no `--promote`, no
`api/ibp.py` — those are the legacy binding-proximity path.

| Endpoint | Reads | Returns |
|---|---|---|
| `GET /map/meta` | `sf_window_meta` (latest window) | run_id, window_start/end, fit_r2, oos_r2, coverage, sf_stability, n_kept |
| `GET /map/constraints` | `constraint_geo` (latest window) | all constraints w/ lat/lon, zone, kv, spread_km, max_abs_sf, binding_hours — the **overlay layer** |
| `GET /map/exposures?sp&k` | `implied_shift_factors` ⋈ `constraint_geo` | top-k constraints driving `sp`: signed `sf`, centroid, max_abs_sf, binding_hours — the **node-explorer click** |
| `GET /map/reach?constraint&k` | `implied_shift_factors` ⋈ geocoded SPs | top-k SPs a constraint drives: signed `sf`, sign split (import/export ends) + the constraint's centroid — the **constraint click** |

The map's node coloring stays **realized congestion** from Phase 0's `/ercot_state_range`;
these `/map/*` endpoints add only the SF structure, not a node-value layer.

Queries are indexed slices:
`… WHERE run_id=? AND window_start=? AND settlement_point=? ORDER BY abs(sf) DESC LIMIT k`
(and the transpose for `/map/reach`). Sub-ms; no per-hour dimension — the SF structure is
fixed per refit, so the explorer is **not** time-indexed (unlike the realized panes).

New response models in `api/models.py`: `MapMeta`, `ConstraintGeo`, `SpExposure` /
`ExposuresResponse`, `ConstraintReach`. All small.

---

## 4. Web — node explorer + constraint overlay

Builds on the Phase-0 SP compare chassis. New pieces, all on the **left (map) pane**:

- **Constraint overlay layer** from `/map/constraints`: markers at each constraint's
  centroid, sized by `max_abs_sf` (or `binding_hours`), toggled like Phase 0's zones layer
  was. Hover → constraint key, zone, support.
- **Node click → `/map/exposures`**: `DetailCard` lists the top-k constraints driving the
  clicked SP — signed exposure ($/MWh per $ of μ), each with fit confidence
  (window `oos_r2`/`sf_stability`) and support. Highlight those constraints' centroids on
  the map.
- **Constraint click → `/map/reach`**: fade all SPs except the ones it drives, colored by
  **signed** `sf` — the positive-SF side and negative-SF side glow opposite ends of the
  diverging palette (the congestion dipole, design §3b). Optional corridor arc between the
  two sign-weighted centroids.

Components mostly exist (`GridMap`, `DetailCard`, `Legend`, `lib/colors.ts`); the new work
is the overlay source, the two click→fetch→highlight flows, and the sign-split reach
rendering.

---

## 5. Realized-μ decomposition (stretch within Phase 1)

The map + **realized** shadow prices already give the oracle layer for any past hour:
`C_realized[sp] = −Σ_c SF[sp,c]·μ_realized[c,t]`. Serving a per-hour
`/map/realized_drivers?ts&sp` (join current SF against realized `M` for that hour) shows
*which constraints actually drove* a node's realized congestion — the causal overlay on
truth, no forecast needed. It's the same slice math as Phase 2's `/forecast/drivers` but
with realized μ instead of `E[μ]`. Worth it if cheap; otherwise defer to Phase 2 and reuse
that machinery. Flag: this is the **oracle**, so label it "realized decomposition," never
"forecast."

---

## 6. Identifiability guardrails (non-negotiable — handoff §4/§5.2)

Grouping did not fix identifiability (R3), so within a co-binding block a single
constraint's signed SF can flip between refits. Therefore:
- **Lead with the stable, unsigned exposure magnitude:** `max_c |SF[sp,c]|` per node and
  `max_abs_sf` per constraint. These are stable (a max over a co-binding block doesn't flip
  even when the within-block allocation does) and ship as the headline.
- **Signed per-constraint exposures are the caveated detail**, always shown with their
  window `sf_stability`/`oos_r2` so a flickering attribution reads as low-confidence.
- **Current refit only.** The explorer serves the latest window; any historic layer is
  labeled as such. Never present a signed exposure without its confidence.

---

## 7. Verification

- **`/map/meta`** returns a real current window with non-null `fit_r2`; `oos_r2`/`coverage`
  present once `compute.sf.eval` backfills them.
- **Exposure/reach are transposes:** `sp` in `/map/exposures?sp=X` lists constraint `c`
  ⇔ `X` appears in `/map/reach?constraint=c`, with the same `sf`.
- **Geo sanity:** a known west-Texas constraint's centroid lands in west Texas; a large
  `spread_km` correlates with bimodal zone_shares (the caution case).
- **Run resolution:** `/map/meta` reports the configured `map-v1` run and its latest
  window; no legacy run or binding-proximity path is reachable.
- **`/run` the app:** click a node → drivers appear with confidence; click a constraint →
  its reach highlights signed; overlay markers sit at plausible locations.

## 8. Order of operations

1. Migration: `constraint_geo` table + `sf_window_meta.sf_stability` column.
2. Compute: run `compute.sf.runner --persist` (`map-v1`); add the geo-persist step (apply
   `geo.constraint_geography` per window → `constraint_geo`); backfill
   `sf_stability`/`oos_r2`/`coverage` via `compute.sf.eval`.
3. API: `/map/*` endpoints + models; set `settings.map_run_id = map-v1`.
4. Web: constraint overlay + node/constraint click flows + signed reach.
5. `/run` + verify (§7).

Compute + API first (independently testable against the DB), then the web layer.

## 9. Out of scope (later phases)

- Any **forecast** (μ heads, propagation, bands, `/forecast/*`) — Phase 2
  (`spec-phase2a-nodal-panel.md`, `spec-phase2b-forecast-day.md`).
- Per-constraint (vs per-window) stability, and constraint **grouping** for display
  legibility (group only for rendering; never attach a signed claim to a group).
- The scoreboard — Phase 3.
- Re-sourcing `/ercot_state_range` off the legacy run (Phase 0 §4 carryover).
