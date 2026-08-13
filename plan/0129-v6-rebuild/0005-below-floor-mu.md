# 0129-0005 - below-floor-mu

Type: feat
Branch: feat/0129-0005-below-floor-mu
Depends on: none — coordinate with `0004` on the constraint-key vocabulary

## Goal

* Serve forecast μ for constraints under the serving floor, as a query filter rather
  than a payload addition.
* Turn the dashed cells in Standouts and Top Constraints from "no opinion" into
  "predicted ~nothing on an element that binds almost daily".

## Context

* `meta.n_constraints` says the day's fit spanned **1,024** constraints; `cast` carries
  the **33** that cleared `meta.params.floor_abs` ($2). A constraint the model priced at
  ~zero is therefore absent from the payload entirely rather than present with a small
  number, so its forecast cells render as a genuine dash.
* This is not a rare edge. **62 elements bound on ≥24 of the last 30 days and 43 are
  outside the cast**, including `BRUNI_69_1` (27 of 30, median Σμ $611, settled $2,724
  on the delivery day). The biggest dashed rows are the most chronic ones.
* The prototype states the fix and its shape directly: *"expected to fall out of the
  rebuild as a query filter rather than a payload change."* This plan is that sentence.
* Size, for the payload-shaped alternative that is being rejected: slim rows (key +
  `mu[24]`) are ~150 bytes — +9 KB for the 62 chronic, +150 KB for all 1,024, against a
  148 KB payload. The reason not to ship them in a blob is architectural, not bytes.
* Naming discipline: a below-floor constraint is one the model **priced near zero**, not
  one it "missed". Do not let this land as blame.

## Approach

* Work in: `api/analysis.py`, `compute/analysis/`
* The full `E_mu` is already in `forecast_sf_artifact` and already decoded by
  `load_sf_mu`. Nothing new is computed — the floor is applied at payload-build time,
  so serving below-floor rows means *not* applying it, under an explicit parameter.
* Expose the floor as a request-side filter (default preserving today's behaviour) so a
  panel asks for what it needs rather than every caller paying for 1,024 rows.
* Coordinate with `0004`: the rollup already reads untruncated `E_mu`, so both plans
  read the same source and must agree on the key vocabulary. Do the vocabulary decision
  once, in whichever lands first.
* Then update the panels that render dashes to distinguish the two cases — *priced near
  zero* (a number) from *not in the fit at all* (a real dash). They currently look
  identical and they are not the same claim.
* Do NOT touch: `floor_abs` / `floor_rel` / `cos_min` as **modelling** parameters. This
  is serving, not modelling; the fit is unchanged.

## Acceptance

* [x] A request can retrieve forecast μ for a constraint below the serving floor — verified with `BRUNI_69_1|DFOAVLO5` on 2026-07-28.
* [x] The new query is key-scoped: it returns every requested constraint represented
  by the fit, including a near-zero forecast, and reports a requested key absent
  from the fit distinctly rather than manufacturing a zero. It has no legacy
  response shape to preserve; the v6 page is its first consumer.
* [ ] `0009` wires Standouts and Top Constraints to this query: they render a number
  where the model priced near zero, and a dash only where the constraint is absent
  from the fit; the two are visually distinguishable.
* [ ] Verify that all 43 chronic-but-uncast elements are represented by the
  2026-07-28 artifact and return forecast values through the query.
* [ ] `0009` marks this field `real` in the live v6 page's data-status UI. The
  static prototype is not a served status source and is left unchanged.
