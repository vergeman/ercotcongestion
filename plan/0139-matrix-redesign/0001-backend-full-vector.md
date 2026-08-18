# 0001 - backend-full-vector

Type: feat
Branch: `feat/0139-matrix-redesign/0001-backend-full-vector`
Source: `plan/0139-matrix-redesign/sprint-matrix-redesign.md`
Depends on: none (can land first)

## Goal

Serve the data the redesign needs. Most already exists — this branch adds one endpoint and
verifies two. History-window work is split into 0004.

## What already exists (reuse, do not rebuild)

* `GET /analysis/node` — full ranked driver column for a node (`terms`, `total`, `coverage`,
  `basis=predicted|realized`, `hours=[...]`). This is the node Read detail.
* `GET /map/reach` — a constraint's node reach (import/export). Params: `k` (default 15, max
  500), `min_frac` (default 0.05 = relative noise floor at `min_frac × peak |SF|`), and now
  `full` (default false) — see step 3.
* `GET /analysis/settlement-points` — full node vocabulary.

## The gap

`GET /analysis/top-constraints` is capped at `k ≤ 15`. There is **no full constraint list**
for search. Build one.

## Files

* Edit: `api/analysis.py` (new endpoint + verify `/node`), `api/models.py` (response models),
  `api/map.py` (`/map/reach` full-reach mode, step 3).
* Edit: `api/tests/` (add tests).

## Steps

1. **Add `GET /analysis/constraints`.** Mirror `/analysis/settlement-points`. Params:
   `delivery_date`, `run_id?`, `horizon?`. Returns every constraint in the daily artifact —
   NOT top-k. For each: `constraint_key`, `name`, `contingency` (split on `|`), `ctype`,
   `zone`, `kv_max`, `binding_hours`, and `daily_mu_rank` + `daily_mu_sum` for default sort.
   Rank by `mu_mass = Σ_ts |E_mu[ts, c]|` over the day (same key `/matrix/frame` uses). Pull
   `ctype`/`zone`/`kv_max` from `constraint_geo` (see `matrix.py::_constraint_types`); absent
   metadata is null, never an error.
2. **Verify `/analysis/node` for the single scrubbed hour.** Confirm a call with
   `hours=[interval_ts]` + `basis=predicted` returns the full `terms` for exactly that hour
   using Forecast μ (`E_mu`), and `basis=realized` uses ERCOT DAM μ (`load_realized_mu`).
   Confirm the client passes the Central-time `delivery_date` derived from `interval_ts`
   (do not break the summer-midnight boundary — mirror `matrix.py::_delivery_date`). Add a
   single-hour test for both bases. Only change plumbing if a case is wrong.
3. **Give `/map/reach` an explicit full-reach mode.** `k` is a display knob (map click, brief) —
   a dev-DB audit found ~half the constraint universe (519/1044, median 495, p95 957, max 1097
   nodes at a 5%-of-peak floor) has real reach past 500 nodes, so raising `k`'s ceiling to cover
   that would conflate "top-k for display" with "give me everything," and still be a guess that
   goes stale as the node universe grows (~1100-1200 settlement points today). Instead: added a
   `full: bool = False` param that drops the `LIMIT` entirely (bounded only by `min_frac`) when
   true, leaving `k` (default 15, max 500 — unchanged) as the map/brief click's own knob. Added
   `truncated: bool` to `ConstraintReach` (mirrors `MatrixFrame.rows_truncated`/`columns_truncated`)
   so any bounded (`full=False`) caller can tell whether more nodes existed above the floor than
   were returned, independent of which mode was used — computed by fetching `k+1` rows and
   trimming, no second `COUNT` query; always `False` when `full=True`. The Read pane must call
   `min_frac=0, full=true`.

## Do NOT touch

* Any `web/` code (0001/0003). The `/matrix/frame` contract. The `/analysis/node` decomposition
  math (`node_contributions` / `_terms`). DAM-unavailable must stay unavailable, never zero.

## Acceptance

* [x] `GET /analysis/constraints` returns the complete constraint universe (not k-capped) with
      `constraint_key, name, contingency, ctype, zone, kv_max, binding_hours, daily_mu_rank,
      daily_mu_sum`; a test asserts count == artifact constraint count.
* [x] `/analysis/node` returns the full driver column for a single `interval_ts` under both
      `predicted` and `realized`, with correct CT delivery-date resolution — test covers both.
* [x] `/map/reach` has a `full` mode (`min_frac=0, full=true`) that drops the row limit entirely
      for the Read pane, and a `truncated` flag so a bounded (`k`-limited) call can tell it was
      cut short — `k`'s own ceiling (500) is unchanged, since it stays the map/brief click's
      display knob, not the matrix's completeness contract.
* [ ] No `web/` changes; `/matrix/frame` unchanged.
