# 0129-0003 - brief-node-rows

Type: feat
Branch: feat/0129-0003-brief-node-rows
Depends on: none

## Goal

> Scope update (2026-08-13): source–sink pairs are no longer a v6 Brief panel.
> The existing `/analysis/path` work remains an API primitive to audit at
> teardown, but this plan has no pending Brief UI or acceptance work for it.

* Serve the **untruncated SF column** for a settlement point — every constraint
  acting on it, not the ones that happened to rank top-5 somewhere — as a
  read-time slice over the already-cached day artifact.
* Serve both on a `predicted | realized` μ basis, so the brief's forecast and
  DAM-settled columns are decomposed the same way.
* Replace the brief panel's dominant-driver column with values computed from the
  full column, and record the coverage ratio that proves it.

## Context

* **Nothing is missing from the model.** The ridge fit produces a dense
  constraints × settlement-points matrix; `implied_shift_factors` stores it
  long-format, sparsified only at `--sf-threshold`; `forecast_sf_artifact`
  carries the whole day's SF + E_mu as one npz blob. The loss is entirely at
  brief serialization.
* `compute/analysis/brief.py:30` sets `TOP_N_NODES = 5` per side per constraint;
  `constraint_node_extrema` (`compute/analysis/families.py:129`) applies it, and
  `assemble.build_brief` writes only that into `analysis_brief`. On 2026-07-28
  the brief's cast of 33 constraints carries **249 SF cells** — ~4% of the
  33 × 177 spanned by the settlement points the panel actually prices, and 0.7%
  of the 33 × 1,115 columns the day's fit produced (`D.meta`: 1,024 constraints
  × 1,115 settlement points).
* **The payload is column-major and truncated, so its transpose does not exist.**
  A node appears only if it placed top-5 on some constraint. A node with fifteen
  mid-sized exposures, none of them top-5 anywhere, has an empty row while still
  carrying a large congestion price.
* Measured cost on 2026-07-28: of 162 nodes in the panel, only **23** had enough
  visible SF to reconstruct 60–160% of their measured `SPP − λ_system`.
  `MCSES_UNIT6` reconstructed to 4%; `CHAR_SLR_RN` to 0%.
* Three prototype columns are therefore measuring **list membership, not
  physics**: the dominant-driver attribution (biggest constraint that *listed*
  the node), the node-pair purity score (dilution terms are the dropped ones),
  and counterparty search (only nodes that made someone's top-5 are candidates —
  which is why `MCSES_UNIT6` returned as the sink of 7 of 12 pairs).
* **The read path already exists and is unused.** `node_drivers`
  (`compute/sf/project.py:233`) computes `contrib[k] = −E_mu[ts,k]·SF[k,sp]` over
  the full column and is documented as the `/forecast/drivers` slice, but no
  route was ever registered (`api/main.py:42-50`). `pair_contributions`
  (`compute/analysis/brief.py:56`) is the pair equivalent and is likewise
  unrouted. `load_daily_artifact` (`api/services/sf_artifacts.py`) already
  decodes and LRU-caches the blob per `(run_id, delivery_date, horizon)`.
* Precedent for the μ basis switch: `/map/constraints/ranked` already serves
  `predicted | realized` over one SF structure, swapping `E_mu` for that day's
  `ercot_dam_shadow_prices` on the same `constraint_name|contingency_name` key
  (`api/models.py:270-283`). Follow it exactly rather than inventing a second
  convention.

## Approach

* Work in: `api/analysis.py`, `api/models.py`, `compute/sf/project.py`,
  `web/` (brief panel).
* Entry point / primary change: new `GET /analysis/node` and
  `GET /analysis/path` on the existing `analysis` router.

* **Do not widen `analysis_brief`.** A full node×constraint expansion is the
  ~240k-rows/day materialization the artifact design exists to avoid
  (`db/migrations/31_forecast_sf_artifact.sql`, `materialize_drivers` docstring).
  The brief document keeps its top-K screening role; these endpoints answer the
  follow-up question the screen provokes. No migration in this plan.

* **Matrix is the shared artifact browser, not this endpoint's payload shape.**
  `/matrix/frame` already loads the same cached `forecast_sf_artifact`, exposes
  the canonical `constraint|contingency` vocabulary, and has the right
  `available=false` behavior when historical blobs are absent. Reuse those
  loaders and the shared realized-DAM-μ block query. Do **not** reuse its
  bounded rectangle: Matrix deliberately caps at 100 rows × 100 columns, ranks
  columns from the selected global constraint screen, and rounds its display
  cells. That is useful for an overview but cannot answer a node's full-column
  question: a node with many mid-sized terms can be absent from the rectangle
  while still carrying material congestion. `/analysis/node` and
  `/analysis/path` are the sparse full-column complement; all attribution and
  coverage math remains unrounded.

* **`GET /analysis/node`** — params `settlement_point`, `delivery_date`,
  `basis=predicted|realized`, optional `run_id`, `horizon`, `hours` (block
  filter, default the whole day), `min_abs_sf` (default `0.0`).
  * Load via `load_daily_artifact`; sum `−μ[ts,c]·SF[c,sp]` over the requested
    hours per constraint. `basis=realized` swaps in DAM μ exactly as
    `/map/constraints/ranked` does.
  * Return **every** constraint with a non-zero term, descending by `|contrib|`,
    plus `total` (their sum) and `n_terms`. No top-k in the response body —
    `min_abs_sf` is the caller's LIMIT, and it defaults to keeping everything.
  * Also return `coverage`: `total / (SPP(sp) − λ_system)` for that block when
    the day has settled, else `null`. **This is the number that proves the fix.**
    It is the 4%/0% figure above, recomputed against the full column.

* **`GET /analysis/settlement-points`** — params `delivery_date`, optional
  `run_id` and `horizon`. Return the artifact's complete, stable settlement-point
  vocabulary for the day. Counterparty discovery fetches this once; it must not
  infer candidates from Matrix's bounded columns or from brief top-5 membership.
  It follows the same `available=false` artifact-missing contract as the two
  attribution endpoints.

* **`GET /analysis/path`** — params `source`, `sink`, and the same day/basis set.
  * `β[c] = SF[c,source] − SF[c,sink]`; `contrib[c] = μ[c]·β[c]`. Use
    `pair_contributions`, which already reconciles exactly to
    `cong[sink] − cong[source]`.
  * Return the full term list plus `spread`, and the **driver-share
    composition** over all terms: `top_share`, `second_share`, `tail_share`,
    `n_terms`, and the top two constraint keys. A share computed on a truncated
    list is meaningless and is the bug this replaces.
  * `top_share` alone is not sufficient and must not be served alone: a 50/50
    pair and a 50/10/10/10/10/10 pair report the same scalar and are a two-name
    bet and a one-name bet respectively. `second_share` is what separates them.
  * Do **not** emit a `focused`/`split`/`diffuse` enum. Those are reader-side
    descriptions of the composition; bucketing them requires a cutoff the data
    does not justify, and a stored label would outlive the numbers that
    motivated it (same reasoning as `constraint_stats`, which reports `top5_share`
    and explicitly leaves *broad/systemic*, *localized pocket* to be derived
    downstream — `compute/analysis/families.py:156`).
  * Naming: "concentration" is deliberately not used — the engine already spends
    that word on the constraint-shape axis (nodes per constraint), this is its
    transpose (constraints per path), and a risk reader reads high concentration
    as danger when here the high end is the good end.
  * Assert the reconciliation in a test, not just in the docstring: the terms
    must sum to the endpoints' congestion difference to within float tolerance.

* **Panel rewiring.** The node panel keeps its top-15 screen from the brief
  document (unchanged, cheap, already correct as a *ranking*), and fetches
  `/analysis/node` for the expanded row. Specifically:
  * dominant driver — the top term of the full column, not of the listed subset;
  * a `coverage` badge on each row, so a node whose visible SF explains 4% of its
    price says so rather than silently attributing to one constraint;
  * the node-pair panel's counterparty search runs over the artifact's full SP
    vocabulary, not over nodes that appeared in some top-5.

* **Ungate the Forecast Grade panel's node half** (`docs/daily_brief_v6_prototype.html`,
  `render4`). This is the second consumer of the truncation and the one that
  currently *displays* the defect rather than merely suffering it.
  * Today the panel scores constraints against the model's full output
    (`X.grade`, read from `forecast_sf_artifact` — 550 rows, 478 forecast) but
    has no equivalent for nodes, because the only node payload on the page is
    the truncated brief. Measured on 2026-07-28: 112 nodes, 183 SF cells, a
    **median of one constraint per node**, and settled-side reconstruction at a
    **median 4%** with only 15 of 111 inside 60–160%.
  * So the node row renders **struck through and labelled `not graded`**, with
    the coverage median printed as the reason. The numbers exist and are
    uninterpretable: bias −0.95 and a median forecast/settled ratio of 0.05 are
    both artifacts of a sum that cannot overshoot, not findings about the
    forecast. `NODES_GRADEABLE` is the single flag holding this.
  * On completion: feed the panel `/analysis/node` coverage per point, flip
    `NODES_GRADEABLE`, and the node row rejoins the headline **unchanged in
    definition** — the metrics were always computed, only withheld. The headline
    then averages constraints and nodes equally (not by count; pooling by count
    would let the node universe set ~70% of every score).
  * Keep the coverage number visible after the fix, not just before it. A node
    whose full column still explains 40% of its price is a different object from
    one at 95%, and the panel should say which.
  * Re-check the bias sign convention when it rejoins: node congestion is
    signed by shift factor, so both halves must be scored on `|congestion|`.
    Scored signed, nodes read +0.49 against the constraints' −0.80 and the
    average nets to −0.16 — a headline reading "balanced" while both halves are
    badly low. This netting trap is why the flag exists in that form.

* **Backfill caveat — state it in the UI, do not paper over it.**
  `forecast_sf_artifact` covers live days but not the bulk-seeded history
  (see the 0103 note). For a delivery date with no blob, both endpoints return
  `available=false` and the panel falls back to the truncated brief columns
  **with the degraded attribution labelled as such**. Do not silently serve the
  old numbers under the new column headings.

* Do NOT touch: `implied_shift_factors`, `compute/sf/fit.py`, or `TOP_N_NODES` /
  `constraint_node_extrema`. The brief document's screening shape is deliberate
  and other consumers read it; this plan adds a second read path beside it.

## Delivery split (API now, web/grade with `0009`)

* **Shipped** (branch `feat/0129-0003-brief-node-rows`): the three endpoints,
  the shared non-DST realized-μ loader, the full-column `node_contributions`
  primitive, float64 reconciliation, and `web/src/api/{client,types}.ts`.
* **Deferred to `0009`**: every panel/grade box below. They presuppose the v6
  page — `AnalysisPage.tsx` is still the old page (replaced in `0009`, torn down
  in `0012`) and `NODES_GRADEABLE` lives only in the prototype — so wiring them
  now is throwaway. The endpoints are ready for `0009` to consume.
* **Pulled forward**: the `|congestion|` bias convention (`congestion_bias` +
  test), the one grade-half item assertable without the page, so `0006`
  inherits a tested primitive.

## Acceptance

* [x] `GET /analysis/node?settlement_point=MCSES_UNIT6&delivery_date=2026-07-28&basis=realized`
      returns > 5 terms and a `coverage` materially above the 0.04 the truncated
      payload implies. Verified against production `mu-all-v1`: 129 terms and
      84.9% coverage.
* [x] `CHAR_SLR_RN` on the same day returns a non-empty term list (it currently
      reconstructs to exactly 0% — it appears in no constraint's top-5).
      Verified against production `mu-all-v1`: 158 terms.
* [ ] `GET /analysis/path` terms sum to `cong[sink] − cong[source]` within 1e-6
      for three sampled pairs, asserted in `api/tests/`.
* [ ] `basis=predicted` and `basis=realized` return the same constraint set
      shape over the same SF, differing only in μ — verified against
      `/map/constraints/ranked` for one day.
* [x] Matrix's exact-hour DAM μ and a one-hour `basis=realized` node/path read
      share one canonical-key, non-DST-preferred loader; a missing DAM key stays
      visibly unmatched in Matrix but contributes zero to full-column arithmetic.
* [x] The v6 node panel reads full-column daily attribution: zone, dominant
      driver, its gross-share, realized coverage, forecast/settled rank and
      delta are server-derived rather than legacy brief-row fields. The 2026-08-12
      local production slice, for example, reports OLNEYTN_AGR1's dominant driver
      as `6830__B|SGRMGRS8` at 44% gross share and 98% realized coverage.
* [ ] Driver share in the node-pair panel is recomputed over full β; the
      previously top-ranked pair either survives or the write-up records why it
      did not. `MCSES_UNIT6` no longer appears as sink in a majority of pairs
      unless the full-column search independently puts it there.
* [ ] `tail_share` rises and `top_share` falls for every pair versus the
      truncated derivation — the direction is guaranteed by construction
      (hidden exposures can only add terms), so any row moving the other way is
      a bug, not a finding. Assert it over a sampled day.
* [ ] At least one pair reclassifies between the focused / split / diffuse
      readings once the full tail is visible, and the panel's second-driver line
      names a constraint that was absent from the truncated payload.
* [ ] A delivery date with no `forecast_sf_artifact` renders the fallback with a
      visible "truncated attribution" marker, and no endpoint 500s.
* [ ] `analysis_brief` schema and contents unchanged — diff one day's brief JSON
      before and after.
* [ ] Forecast Grade panel: `NODES_GRADEABLE` flips true, the node row loses its
      strikethrough and `not graded` status, and the headline tiles average both
      halves. Coverage median moves off 4% and stays displayed.
* [x] The node half's bias is computed on `|congestion|`, asserted by a test —
      the signed form nets against the constraint half and reports "balanced"
      when both halves are low. `congestion_bias` + test; grade-panel wiring
      deferred to `0009`.
* [ ] Same day scored before and after: record which of the three headline
      numbers moved and by how much. The node metrics are unchanged in
      definition, so any movement is the truncation being removed and should be
      attributable to it.
