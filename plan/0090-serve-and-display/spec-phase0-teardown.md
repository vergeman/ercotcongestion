# Spec — Phase 0 teardown & `/topology` repoint

**Context:** `serving-and-display-design.md` Phase 0. Retire the synthetic-grid
serving, repoint `/topology` onto the geocoded settlement points, and collapse the web
app to a settlement-point map — leaving a coherent, runnable app on realized ERCOT data
that the forecast (Phase 2) slots into. Decisions already locked: delete the legacy
endpoints (cheap to resurrect via git); forecast-left / realized-right is the design of
record (§2 of the design doc).

**Nature of this change:** it is mostly *subtraction*, but it is a **coupled API + web
change** — dropping the synthetic buses from `/topology` breaks the web app's left pane,
so both sides move together (§2). No new data, no modeling.

---

## 1. The coherent-boundary decision (read first)

The forecast that will fill the **left pane** does not exist until Phase 2. So Phase 0
must pick an interim left-pane source or it leaves the app broken. Options:

- **(A, recommended) Keep the two-map chassis; both panes become ERCOT SP layers on
  realized data.** Left = realized congestion (`/ercot_state_range`), right = realized SPP
  (`/ercot_spp_range`) — or left = lmp, right = congestion. The app stays
  functional and *looks like the product*; Phase 2 swaps the left source to the forecast
  with no further chassis work.
- (B) Collapse to a single map until Phase 2. More churn now, and it throws away the
  camera-sync/compare code Phase 2 needs back.

**Adopt (A).** Everything below assumes the compare chassis survives and only its data
sources change.

---

## 2. API teardown

### 2.1 Routes
| Route | File | Action |
|---|---|---|
| `/state`, `/state_range` | `api/state.py` | **delete** — synthetic PyPSA bus state |
| `/validation` (scorecard) | `api/validation.py` | **delete** — clustering scorecard |
| `/ptdf` | `api/ptdf.py` + `api/services/ptdf_service.py` | **delete** — synthetic PTDF |
| `/topology` | `api/topology.py` + `api/services/topology_builder.py` | **rewrite** → SPs only (§3) |
| `/ercot_state_range` | `api/ercot_state.py` | **keep** — realized congestion (§4) |
| `/ercot_spp_range` | `api/ercot_spp.py` | **keep** — realized SPP (clean, reads `ercot_dam_spp`) |
| `/ibp/ercot[_range]` | `api/ibp.py` | **delete** — legacy binding-proximity panel; bp is not served (the map value is congestion) |
| `/meta` | `api/meta.py` | **keep** (trim of legacy `ref/algo/k` + IBP-pointer read deferred) |

`api/main.py`: drop `state, validation, ptdf, ibp` from the import line and their four
`include_router(...)` calls; update the URL comment.

### 2.2 Models (`api/models.py`)
**Delete** (only the deleted routes use them): `BusState`, `BindingLine`, `Contingency`,
`ZoneOutage`, `SnapshotMeta`, `StateResponse`, `StateRangeEntry`, `StateRangeResponse`,
`ScorecardZone`, `ScorecardHeadline`, `ScorecardSeries`, `ScorecardParams`,
`MappingCorrelationSummary`, `ScorecardResponse`, the unused `TopologyResponse`
(the route returns a raw `JSONResponse`, not this model), and the `IbpErcot*` models
(`IbpErcotPoint`, `IbpErcotResponse`, `IbpErcotRangeEntry`, `IbpErcotRangeResponse`).
**Keep:** `ErcotSpState` / `ErcotStateRange*`, `ErcotSpSpp` / `ErcotSppRange*`, `MetaResponse`.

### 2.3 Why the deletions are safe (verified, not assumed)
- **No kept module imports the deleted symbols.** `grep` across `api/` for the deleted
  models/services returns only their own files and the tests — `ercot_state`, `ercot_spp`,
  `meta` import none of them. (`meta` reads the legacy IBP pointer *table* by raw SQL, not
  via `api/ibp.py`, so deleting the ibp route/models doesn't break it; that read just
  returns null — trim deferred.)
- **`ercot_state` and `meta` read `scorecard.json` as a *file*** (`json.load` of
  `<served_run_dir>/mapping/scorecard.json`), **not** via the `Scorecard*` models or the
  `/validation` route. Deleting the models and the route leaves those file reads intact —
  they only pull the `params.ref` / `params` strings. So the kept endpoints keep working.

### 2.4 Tests
- **Delete:** `test_state.py`, `test_validation.py`, `test_integration.py` (the last only
  exercises `/state` + `/state_range`), `test_ibp.py` (route deleted).
- **Rewrite:** `test_topology.py` → assert the payload is `settlement_points`-only, no
  `buses`/`lines`; `test_openapi.py` → assert the deleted schemas (including `IbpErcot*`)
  are **absent** and the kept ones (`ErcotStateRangeResponse`, `MetaResponse`) present.
- **Keep:** `test_meta.py`.

### 2.5 Config (optional cleanup)
After the builder rewrite, `NETWORK_NC`, `BUS_WEATHER_LOAD_ZONES_CSV`,
`GENERATOR_MATCHES_ENRICHED_CSV` in `api/config.py` are unused. Trimming is optional and
low-value; leave or remove in the same PR, not a follow-up debate.

---

## 3. `/topology` rewrite (builder simplification)

`api/services/topology_builder.py` already reads
`settings.settlement_points_geocoded_csv` in `_settlement_points_feature_collection` — the
rewrite is deletion around that function.

**Keep:** `_sp_load_zone_from_name` (name-prefix → load_zone), the disk-cache +
atomic-write scaffold, `get_or_build_topology(force)`, the `__main__` block.
**Delete:** the `import pypsa` network load, `_buses_feature_collection`,
`_lines_feature_collection`, `_load_bus_cluster_labels`, `_load_sp_cluster_labels`,
`_load_zone_polygons`, `_cluster_labels_key`, and the cluster-keyed cache invalidation.

**New shape:**
```python
def build_topology() -> dict:
    return {'settlement_points': _settlement_points_feature_collection()}
```
- SP feature `properties`: `sp_id`, `sp_type`, `load_zone`, `capacity_mw`
  (from `matched_capacity_mw`, for node sizing). **Drop** `cluster_id` / `best_corr`
  (legacy-run derived).
- `_cache_is_current`: stale if the cache carries `buses`/`lines` (legacy schema) or its
  SP features lack `capacity_mw`. A legacy cache then auto-rebuilds on first hit.
- The route (`api/topology.py`) is unchanged except its docstring/description; it keeps
  returning `JSONResponse` with the 24 h `Cache-Control`.

**Result:** `/topology` returns ~1,092 geocoded SP points and nothing synthetic.

---

## 4. The `ercot_state` entanglement (note, not a Phase-0 fix)

`/ercot_state_range` serves realized congestion from the **legacy run's**
`congestion_matrices.npz` + `scorecard.json` `params.ref`. It is kept working as-is for
Phase 0 (still returns realized SPP − system_λ), but it is *entangled with the served
legacy run*, unlike `/ercot_spp_range` which reads the clean `ercot_dam_spp` table. Re-sourcing
it to a run-independent realized table is deferred to the serving-plan §4.3
`/realized/congestion_range` work — flagged here so nobody mistakes "kept" for "clean".

---

## 5. Web teardown (`web/`)

### 5.1 API client (`web/src/api/client.ts`)
- **Delete:** `fetchState`, `fetchStateRange`, `fetchScorecard`, `fetchPtdf`,
  `fetchIbpErcotRange` (route deleted).
- **Keep:** `fetchTopology` (consumers change), `fetchErcotStateRange`,
  `fetchErcotSppRange`.
- `web/src/api/types.ts`: delete `BusState`(model-side), `SnapshotMeta`, `State*`,
  `Scorecard*`, `MappingCorrelationSummary`, `Ptdf*`, `IbpErcot*`, `BusFeatureProperties`,
  `LineFeatureProperties`; keep the Ercot*/SP types. Repoint `SPFeatureProperties`
  to drop `cluster_id`/`best_corr`, add `capacity_mw`.

### 5.2 App shell (`web/src/App.tsx`) — the coupled collapse
Under decision (A), both panes render SP layers on realized data:
- Remove the synthetic **model pane**: the `topology` buses branch, `buses`/`meta` state,
  `fetchState*`, `SnapshotMeta`, bus hover/click/pin, the sparkline meta series.
- Remove **scorecard/zones**: `scorecard`, `selectedClusterId`, `showZones`,
  `tightClusterIds`, `handleSelectCluster`, and the `StatsPanel` scorecard wiring.
- Keep the `CompareMap` + camera-sync + `PlaybackScrubber` + `DateRangePicker` +
  curated-events chassis. Point **left** = `/ercot_state_range` (realized congestion),
  **right** = `/ercot_spp_range` (SPP). Both use the existing `spTopology` (SP-as-bus
  alias) path, which already exists.
- `ViewMode` collapses to ERCOT palettes only (`congestion` / `lmp`);
  drop `modeled_congestion` as a *model-side* mode.

### 5.3 Components
- **Delete/retire:** anything model-bus- or scorecard-specific — the `StatsPanel`
  scorecard section, zones legend, PTDF overlays, `CompareMap`'s model-side assumptions.
- **Keep:** `GridMap`, `Legend`, `DetailCard`, `CompareMap`, `PlaybackScrubber`,
  `TimelineSparkline`, `DateRangePicker`, `lib/colors.ts`, prefetch/cache.
- `web/src/api/prefetch.ts`: drop the `getCached`/model-state fan-out; keep the ERCOT
  congestion/SPP/bp caches.

*(5.2–5.3 are the largest single chunk of Phase 0 and the part most worth a careful diff;
the API side is mechanical by comparison.)*

---

## 6. Verification

- **API imports clean:** `main.py` loads with the three routers gone; `/openapi.json`
  omits the deleted schemas (the rewritten `test_openapi.py` asserts this).
- **`/topology`:** returns `settlement_points` only, ~1,092 features with
  `sp_id/sp_type/load_zone/capacity_mw`, no `buses`/`lines`; a stale legacy cache rebuilds.
- **Kept endpoints unaffected:** `test_meta.py` passes; `/ercot_state_range`
  and `/ercot_spp_range` still return realized data.
- **Web runs:** `npm run build` clean (no dangling imports of deleted client fns/types);
  the app loads a single ERCOT SP map with a working scrubber and no synthetic pane.
- **`/run` the app** end-to-end to confirm the compare view renders realized data both
  sides before calling Phase 0 done.

---

## 7. Order of operations

1. API: rewrite `topology_builder.py` → SP-only; trim `models.py`; edit `main.py`;
   delete `state/validation/ptdf` files + their tests; rewrite `test_topology.py` /
   `test_openapi.py`. Run `pytest`.
2. Web: trim `client.ts` / `types.ts`; collapse `App.tsx` + components/prefetch to the
   ERCOT-only compare view. Run `npm run build` + `/run`.
3. Commit on a branch (`git rm` keeps the deleted files one `git revert` away).

Do the API half first — it is self-contained and testable — then the web half against the
already-repointed API.

## 8. Out of scope (later phases)

- Serving the SF map / node explorer / constraint geography (Phase 1).
- The forecast nodal panel + SF+μ artifact + forecast endpoints (Phase 2,
  `spec-phase2a-nodal-panel.md` / `spec-phase2b-forecast-day.md`).
- Re-sourcing `/ercot_state_range` off the legacy run (§4).
- Deleting the legacy compute promote/symlink/clustering machinery — this spec unmounts
  *serving routes* only; the OPF/synthetic compute + writeup stay (design doc §8).
