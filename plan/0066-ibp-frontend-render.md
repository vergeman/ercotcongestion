# 0066 - ibp-frontend-render

Type: feat
Branch: feat/0066-ibp-frontend-render

## Goal

* Populate the right (ERCOT) pane on the **Binding Proximity** tab from
  `GET /ibp/ercot` — SP topology colored by promoted `bp_ercot`, replacing
  today's `ERCOT · no comparable signal for binding proximity` placeholder.
* Keep the paired MC / LMP panes untouched; BP is the only new right pane.
* Make hover / pin over an SP show `bp` in the DetailCard and render the
  proximity gradient in the right-pane Legend.

## Context

* Backend already serves a promoted `bp_ercot` panel via `GET /ibp/ercot?ts=...`
  ([plan 0065](0065-ibp-api-endpoint.md)); ingest + pointer flip landed in
  [plan 0064](0064-ibp-frontend-ingest.md).
* Frontend has the palette (`bindingProximityColor`, `normalizeProximity`,
  `BINDING_PROXIMITY_ANCHORS`) and SP topology in `/topology.settlement_points`
  — both are already reused by MC and LMP right panes.
* `App.tsx:57 rightPaneFor()` currently returns `"empty"` for BP; that's the
  only code path that keeps the placeholder alive. Everything downstream
  (`GridMap`, `Legend` with `isProximity`, `DetailCard` SP body) already
  handles the color path — the missing piece is data + wiring.
* Prefetch is window-based (`prefetchWindow` in `api/prefetch.ts`); the
  per-hour `/ibp/ercot` endpoint alone would need N calls per window. We add
  a range sibling that mirrors `/ercot_spp_range`.

## Discussion — decide before implementing

**D1 — Serve BP as a range or per-hour.** Options:
* **(a) Add `GET /ibp/ercot_range?start=&end=`** returning
  `{start, end, count, run_id, entries: [{interval_ts, points}]}`. One
  round-trip per window; slots into the existing `prefetchWindow` fan-out
  alongside `fetchStateRange` / `fetchErcotStateRange` / `fetchErcotSppRange`.
  **Recommended.** Payload is bounded (~4k SPs × 24–96 hrs × ~16 bytes/pt
  ≈ 1–4 MB per typical window, gzipped).
* **(b) Fan out N calls to the per-hour endpoint from the client.**
  Simpler backend, worse latency and cache-key sprawl. Reject.

**D2 — Where to carry BP on the client cache.** Options:
* **(a) New `ibpErcotCache` map** parallel to `ercotCache` / `ercotSppCache`
  in `api/prefetch.ts`, one entry per hour with `{points}`. Union merged
  into `ercotBuses` (setting the existing `binding_proximity` field on the
  SP-shaped `BusState`). **Recommended** — matches how the MC + SPP union
  is built today (`App.tsx:262-286`).
* **(b) Widen `ercotCache` to carry BP too.** Muddles the "SPP − system_λ"
  contract of that cache. Reject.

**D3 — `run_id` presentation.** Options:
* **(a) Show `run_id` in the right-pane badge** (e.g. `ERCOT · 4126 SPs ·
  3892 lit · ibp_w60_r7_l1e-2`). No new UI real estate; users can see which
  run they're looking at. **Recommended.**
* **(b) Hide it.** Fine day-one, but promoting a run then not being able to
  tell from the map is a common failure mode we already hit with matrix runs.

**D4 — Behavior when no BP run has been promoted (404 / 503).** Options:
* **(a) Soft-fail the range fetch to `null`** (`fetchIbpErcotRange` returns
  `null` on 503; the empty placeholder shows with a "no run promoted yet"
  message). Same contract as `fetchErcotStateRange` and `fetchErcotSppRange`.
  **Recommended.**
* **(b) Hard error.** Kills the tab. Reject.

**D5 — BP DetailCard row.** Options:
* **(a) Add a `Binding Proximity` row to `SpBody`** — parallel to the
  existing bus-side row (`DetailCard.tsx:74`). Read from `spState.bp`.
  **Recommended.**
* **(b) Only badge it, no detail card.** Loses the "what's the number here"
  affordance users have on every other pane.

## Approach

Assuming defaults above. Four sections = four commits.

### Commit 1 — backend: `/ibp/ercot_range`

* Work in: `api/ibp.py`, `api/models.py`, `api/tests/test_ibp.py`.
* Add response models in `api/models.py`:
  ```python
  class IbpErcotRangeEntry(BaseModel):
      interval_ts: datetime
      points: list[IbpErcotPoint]

  class IbpErcotRangeResponse(BaseModel):
      start: datetime
      end: datetime
      count: int
      run_id: str
      entries: list[IbpErcotRangeEntry]
  ```
* Endpoint: `GET /ibp/ercot_range?start=<iso>&end=<iso>` in `api/ibp.py`.
  Same two-step shape as the per-hour endpoint:
  1. Resolve `run_id` from `implied_binding_proximity_current[ercot]`. If
     missing → **503** (`"no implied_binding_proximity run promoted for layer 'ercot'"`),
     matching the soft-fail contract the client expects for ERCOT-side ranges.
     *Rationale: 404 is the right answer for a specific-hour GET, but 503
     signals "backend artifact not built" — which is exactly what the client's
     `fetchErcotSppRange` already interprets as "render model side alone."*
  2. Single query: `SELECT ts, settlement_point, bp FROM implied_binding_proximity
     WHERE run_id = %s AND ts BETWEEN %s AND %s`. Group by `ts` in Python.
* Hours with no rows: include an entry with `points: []` (parity with
  `/ibp/ercot` returning empty on missing hour). Only the entire window
  being empty is an error (503 with `"no implied_binding_proximity rows in
  window ..."`).
* Follow `api/ercot_spp.py` for UTC coercion, `dict_row` cursor style, logging.
* Tests in `api/tests/test_ibp.py`:
  * Range returns grouped entries + `run_id`.
  * 503 when nothing promoted.
  * 503 when pointer exists but no rows in window.
  * Hour inside window with no rows → entry present with `points: []`.

### Commit 2 — frontend API layer

* Work in: `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/api/prefetch.ts`.
* `types.ts` — add:
  ```ts
  export interface ErcotSpBp { sp_id: string; bp: number | null; }
  export interface IbpErcotRangeEntry {
    interval_ts: string;
    sps: ErcotSpBp[];
  }
  export interface IbpErcotRangeResponse {
    start: string; end: string; count: number;
    run_id: string;
    entries: IbpErcotRangeEntry[];
  }
  ```
  *Rename `settlement_point` → `sp_id` at the wire boundary so the shape
  matches the other ERCOT-side range types the client already consumes.*
* `client.ts` — add `fetchIbpErcotRange(start, end): Promise<IbpErcotRangeResponse | null>`.
  Returns `null` on 503, throws otherwise. Mirror `fetchErcotSppRange`.
* `prefetch.ts` — add:
  * `ibpErcotCache: Map<string, IbpErcotRangeEntry>` and `promotedIbpRunId: string | null` module-level.
  * `getIbpErcotCached(ts)` and `getIbpPromotedRunId()`.
  * Extend `prefetchWindow` to `Promise.all([...existing, fetchIbpErcotRange(start, end)])`
    and, when non-null, seed the cache using the same `roundToInterval`
    key + first-write-wins guard the other ERCOT caches use.
  * Extend `clearCache` to clear the new cache and reset `promotedIbpRunId`.

### Commit 3 — frontend render: SP topology colored by BP

* Work in: `web/src/App.tsx`, `web/src/components/map/Legend.tsx` (small).
* `App.tsx`:
  * `RightPaneKind`: add `"ercot_bp"`. `rightPaneFor("binding_proximity")` → `"ercot_bp"`.
  * Keep `"empty"` as a valid state, but only for the case where the range
    fetch returned `null` (no run promoted). Track a `bpAvailable` boolean
    set by `handleLoadWindow` based on whether `getIbpPromotedRunId()` is set
    after prefetch.
  * Extend the snapshot effect (`App.tsx:249-290`): when hour cache has a
    BP entry, merge `binding_proximity: sp.bp` into `ercotBuses` using the
    same "union by sp_id" pattern already there for MC + SPP. This lets the
    existing GridMap effect (`GridMap.tsx:679`) color the right pane with
    `bindingProximityColor(normalizeProximity(bus.binding_proximity))` with
    zero new code in `GridMap`.
  * Right-pane render branch: when `rightKind === "ercot_bp"` and
    `bpAvailable`, render `<GridMap ... viewMode="binding_proximity" side="ercot" />`
    — same structure as `ercot_spp` / `ercot_congestion` branches. Badge
    label: `` `ERCOT · ${feats} SPs · ${lit} lit · ${runId}` ``.
  * When `rightKind === "ercot_bp"` but `!bpAvailable`, keep the existing
    placeholder pane but change the copy to `` `ERCOT · no bp_ercot run
    promoted yet` `` so operators know it's an ingestion state, not a
    modeling gap.
  * `spStateFor`: widen the return type to also carry `bp` so the DetailCard
    can pick it up (used in Commit 4).
* `Legend.tsx`:
  * The Proximity branch already renders in `variant="palette-only"`; verify
    it fires when the App passes `viewMode="binding_proximity"` for the
    right pane. No layout changes needed — just make sure App passes the
    correct `viewMode` (not the hardcoded `lmp`/`modeled_congestion` fallback
    on `App.tsx:544`).
* Do NOT change `GridMap.tsx` — it already handles BP coloring on any
  topology / bus source.

### Commit 4 — DetailCard + interaction polish

* Work in: `web/src/components/map/DetailCard.tsx`, `web/src/App.tsx`
  (`HoveredSp` type only).
* Extend `HoveredSp.spState` to `{ congestion, spp, bp } | null` in `App.tsx`;
  populate `bp` from the `ercotBuses` row that Commit 3 seeded.
* `SpBody`: add a `Binding Proximity` row rendered as `${(bp*100).toFixed(1)}%`
  (matches the bus-side row at `DetailCard.tsx:74-80`). Omit when
  `spState.bp` is null.
* Right-pane badge shows the promoted `run_id` from `getIbpPromotedRunId()`
  (already wired in Commit 3; this commit just tightens the string).
* Do NOT touch: `Legend.tsx`, `GridMap.tsx`, backend.

## Acceptance

* [ ] `GET /ibp/ercot_range?start=...&end=...` returns a range payload
      with `run_id` and one entry per hour (empty `points` allowed).
      503 when nothing promoted or window is empty.
* [ ] Selecting the **Binding Proximity** tab renders the ERCOT SP
      topology on the right pane, colored by `bp` on the sequential
      slate→amber→red palette.
* [ ] Scrubbing the timeline updates the right pane in lockstep with the
      left (both draw from the prefetched window).
* [ ] Hover / pin an SP → DetailCard shows a `Binding Proximity` row
      formatted as a percentage.
* [ ] Right-pane badge shows the promoted `run_id` (visible & stable
      across scrubs within a window).
* [ ] Flipping the promoted pointer + loading a new window swaps
      `run_id` in the badge without a redeploy.
* [ ] No BP run promoted → right pane shows `ERCOT · no bp_ercot run
      promoted yet` and the left (model) pane still renders normally.
