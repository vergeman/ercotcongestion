# 0065 - ibp-api-endpoint

Type: feat
Branch: feat/0065-ibp-api-endpoint

## Goal

* Serve the promoted `bp_ercot` panel from Postgres via a FastAPI endpoint.
* Resolve which run to serve from `implied_binding_proximity_current` so
  promoting a new run does not require a redeploy.
* Match the response shape the map's ERCOT layer already consumes.

## Context

* Plan 0064 landed the DB tables (`implied_binding_proximity`,
  `implied_binding_proximity_current`) and the `compute.implied_binding_proximity.ingest` CLI.
* Existing pattern to mirror: `api/ercot_spp.py` — window-based query, UTC
  coercion, `dict_row` cursor, Pydantic response model in `api/models.py`.
* Frontend today reads bp_ercot off disk / a static file; wiring the API is
  what lets the map pick up a promoted run without a redeploy.

## Discussion — decide before implementing

**D1 — Response grain.** Options:
* **(a) Per-hour endpoint**: `GET /ibp/ercot?ts=...` returns
  `{ts, run_id, points: [{sp, bp}, ...]}`. One SQL round-trip per map tick.
  Cheapest per response. **Recommended if the map only shows one hour.**
* **(b) Range endpoint**: `GET /ibp/ercot_range?start=...&end=...` returns a
  panel. Matches `ercot_spp_range`. Bigger payloads; only pick this if the
  frontend needs scrubbing.

**D2 — Pointer resolution.** Options:
* **(a) Subselect per request**: `WHERE run_id = (SELECT run_id FROM
  implied_binding_proximity_current WHERE layer = 'ercot')`. Always fresh,
  one extra index hit. **Recommended.**
* **(b) Cache in-process** with TTL. Faster but adds a staleness window on
  promotion — not worth it at this traffic level.

**D3 — Missing SPs.** If a settlement point has no row for the requested
hour (bp not defined for that (run, hour, sp)):
* **(a) Omit from response.** Frontend already handles missing SPs.
  **Recommended.**
* **(b) Return `null`.** Explicit but bulkier.

## Approach

Assuming defaults above.

* Work in: `api/ibp.py` (new), `api/models.py` (add response models),
  `api/main.py` (mount the router).
* Endpoint: `GET /ibp/ercot?ts=<iso8601>` →
  `IbpErcotResponse { ts, run_id, points: [{settlement_point, bp}] }`.
* Query:
  ```sql
  SELECT settlement_point, bp
  FROM implied_binding_proximity
  WHERE ts = %s
    AND run_id = (
      SELECT run_id FROM implied_binding_proximity_current
      WHERE layer = 'ercot'
    )
  ```
* Return 404 if the pointer row is missing (nothing promoted yet).
* Return 200 with `points: []` if the pointer resolves but the requested
  `ts` has no rows — that's a valid "no bp for this hour" state, not an
  error.
* Follow `api/ercot_spp.py` for UTC coercion, logging, and cursor style.
* Do NOT modify `compute/implied_binding_proximity/`. This is API only.

## Acceptance

* [x] `GET /ibp/ercot?ts=<hour>` returns 200 with `run_id` matching
      `implied_binding_proximity_current.ercot` and the expected SP list.
* [x] Flipping the pointer (`ingest --promote`) makes the next request
      return the new `run_id` without a restart.
* [x] No promoted run → 404 with a clear message.
