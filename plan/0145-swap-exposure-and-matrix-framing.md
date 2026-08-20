# 0145 - swap-exposure-and-matrix-framing

Type: feat
Branch: feat/0145-swap-exposure-and-matrix-framing

## Goal

* Re-frame the map's node card as **what actually drove this node** — rank by
  contribution (`−μ × SF`) at the cursor hour, drop `μ = 0` rows.
* Keep the structural `|SF|` ranking reachable behind a secondary toggle.
* Make the matrix the **holistic** surface: keep zeros and clipped ±1, add
  Forecast μ and ERCOT DAM μ columns, and mark clipped SFs with `*`.

## Context

* Three surfaces read the same artifact SF and agree on every value, but rank and
  filter differently, with nothing on screen saying so — the cause of three
  successive "these don't match" reports (0144, and the two follow-ups).
  `/map/exposures` ranks by `|SF|` unfiltered; the matrix ranks by day
  contribution, top-30/100; `/analysis/node` ranks by `|−μ × SF|` and drops `μ=0`.
* The map card currently leads with constraints that did not bind that day. For
  `RHESS2_ESS1` on 2025-02-20 its top entry (`HEXT_YELWJC1_1|SFORYEL8`, SF −1.000)
  had `μ = 0` for all 24 hours, while the constraint that actually moved 76% of
  the node's congestion (`1680__A|DTMPBE58`, μ 37.36) ranked third.
* **Clipping needs no pipeline change.** `compute/sf/fit.py` clips to exactly
  `±SF_ABS_CAP = 1.0`, so `|SF| >= 1.0` is an exact serve-time test for a clipped
  cell. `n_clipped` is computed in the fit but dropped before serving; do not
  revive it — infer at read time instead. 24 of 864,057 cells (0.003%) are
  clipped in the 2025-02-20 artifact.
* Clipped cells matter out of proportion to their count: a clipped value is by
  construction the maximum possible `|SF|`, so under `|SF|` ranking it always
  sorts first. 12 of 983 nodes have their top exposure set by one.

## Approach

* Work in: `api/map.py`, `api/models.py`, `web/src/api/client.ts`,
  `web/src/api/types.ts`, `web/src/components/map/DetailCard.tsx`,
  `web/src/components/matrix/MatrixGrid.tsx`.
* Entry point: `get_map_exposures`.

### Exposures → actual drivers

* Add `rank: str = Query("contribution", pattern="^(contribution|sf)$")`.
* `contribution` (new default): compute `−μ × SF[:, sp]` at the cursor hour from
  the artifact's `E_mu`, drop zero terms, order by `|contribution|` desc. Reuse
  the existing shared helper `compute.sf.project.node_contributions` — the one
  `/analysis/node` already calls — so the two cannot drift. (No extraction from
  `analysis.py` was needed; the shared helper predates this plan.)
* `sf`: today's `|SF|` ordering, unchanged, for the toggle.
* Carry `contribution` and `mu` per row on `SpExposure`, and `node_total` — the
  signed sum over *all* constraints, so a row's share stays honest under top-k.
  All three are `None` under `rank=sf`.
* With `t` omitted, keep contribution ranking and sum the whole block, which is
  the roll-up `/analysis/node` performs without an `hours` filter. Do **not**
  silently switch to `sf` ordering: a basis that changes itself without saying so
  is the class of defect this plan exists to remove.

### Clipping

* Add `sf_clipped: bool` to `SpExposure`, set from `abs(sf) >= SF_ABS_CAP`.
* The matrix carries the threshold, not a mask: one `sf_abs_cap: float` on
  `MatrixFrame` instead of a `row_count x column_count` boolean array. The clip
  is exact, so the client's `abs(v) >= sf_abs_cap` is the same test the server
  would apply, and the payload stays the size it is today.
* Render as a trailing `*` with a legend/tooltip explaining it is a ridge
  artifact on a poorly-conditioned column, not a measured value.

### Matrix

* Add Forecast μ and ERCOT DAM μ as two persistent columns beside the row header
  (both already on `MatrixRow`; today they appear only in the hover tooltip).
* Keep the existing unfiltered/zero-inclusive behaviour — the matrix is the
  holistic view and must keep showing structurally-real-but-quiet constraints.
* Label each surface's ranking basis in its header, so the difference is visible
  rather than inferred.

* Do NOT change the SF fit, the clip cap, or any persisted artifact — this is a
  read/presentation change end to end.

## Acceptance

* [x] `/map/exposures?...&t=...` defaults to contribution order, excludes `μ=0`
      rows, and matches `/analysis/node`'s `terms` order and values. Verified on
      dev (`AEEC`, 2026-08-13T18Z): top 8 keys, SFs, and contributions identical,
      and `node_total` equals the node endpoint's `total` to the last digit.
* [x] `rank=sf` reproduces today's ordering. Same node/hour still leads with
      `6033__A|DTVWJON5` at #2 — a constraint absent from the contribution top 8,
      which is precisely the reported "mismatch".
* [x] `t` omitted keeps contribution ranking over the block sum, without erroring.
* [x] Rows with `|SF| >= SF_ABS_CAP` carry `sf_clipped: true` and render with `*`;
      no other row does.
* [x] The matrix shows both μ values side by side, still lists zero-μ and clipped
      rows, and its totals/rankings are unchanged.
* [x] Each surface states its ranking basis on screen (card header + toggle;
      matrix corner "ranked by day contribution · unfiltered").
* [x] 5 new tests verified red against the pre-change endpoints, then green.
      Full API suite: 140 passed, same 3 pre-existing `test_analysis.py` failures
      as HEAD (0143.2). Web typecheck and `vite build` clean; eslint at the HEAD
      baseline of 41.

## Not verified

* Visual layout of the new card rows and matrix header was not rendered in a
  browser: Vite's dev server rejects the probe container's Host header. The
  contract underneath it is verified against live dev data.
