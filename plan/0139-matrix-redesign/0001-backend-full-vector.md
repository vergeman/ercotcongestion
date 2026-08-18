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
  500) and `min_frac` (default 0.05 = relative noise floor at `min_frac × peak |SF|`).
* `GET /analysis/settlement-points` — full node vocabulary.

## The gap

`GET /analysis/top-constraints` is capped at `k ≤ 15`. There is **no full constraint list**
for search. Build one.

## Files

* Edit: `api/analysis.py` (new endpoint + verify `/node`), `api/models.py` (response model).
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
3. **Record the reach call for the Read pane.** No code change to `/map/reach`. Document that
   the constraint Read view must call it with `min_frac=0` and a high `k` (e.g. 500) so both
   import and export lobes come back complete; the UI folds the sub-threshold tail. Note if
   any real constraint exceeds `k=500` (then raise the max).

## Do NOT touch

* Any `web/` code (0001/0003). The `/matrix/frame` contract. The `/analysis/node` decomposition
  math (`node_contributions` / `_terms`). DAM-unavailable must stay unavailable, never zero.

## Acceptance

* [ ] `GET /analysis/constraints` returns the complete constraint universe (not k-capped) with
      `constraint_key, name, contingency, ctype, zone, kv_max, binding_hours, daily_mu_rank,
      daily_mu_sum`; a test asserts count == artifact constraint count.
* [ ] `/analysis/node` returns the full driver column for a single `interval_ts` under both
      `predicted` and `realized`, with correct CT delivery-date resolution — test covers both.
* [ ] The `/map/reach` full-reach call (`min_frac=0`, `k=500`) is documented; `k` max raised if
      any constraint needs it.
* [ ] No `web/` changes; `/matrix/frame` unchanged.
