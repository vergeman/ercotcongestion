# 0149 - cancellation-safe-driver-shares

Type: fix
Branch: fix/0149-cancellation-safe-driver-shares

## Goal

* Replace unbounded signed-net driver percentages with bounded gross-magnitude shares.
* Preserve each constraint's signed $/MWh contribution.
* Expose the full-constraint gross denominator so top-k rows remain honest.

## Context

* The node DetailCard divided a contribution by `node_total = Σ contribution`.
* At quiet nodes, positive and negative constraints can nearly cancel, making a small term appear as an extreme percentage (for example, `−648%`).
* The requested node/hour was `WHCCS2_4` at 2026-06-30T06Z; contribution is currency congestion (`$/MWh`), not MW/h.

## Approach

* Work in: `api/map.py`, `api/models.py`, `web/src/api/types.ts`, `web/src/components/map/DetailCard.tsx`, and `api/tests/test_map.py`.
* Entry point / primary change: `get_map_exposures` and `ExposuresBody`.
* Replace the unused `node_total` response field with `node_gross_total = Σ |contribution|` for contribution-ranked responses.
* Return the gross total over all nonzero constraints, not merely the displayed top-k; return it as `null` in structural (`rank=sf`) mode.
* Rename the contribution-column percentage to `Gross` and render `|contribution| / node_gross_total`; document in its tooltip that opposing signs do not cancel.
* Cover same-sign, offsetting-sign, and `rank=sf` response behavior in the exposure tests.
* Do NOT touch: SF fitting, μ forecasts, contribution ranking, artifact persistence, or the signed contribution values.

## Acceptance

* [x] A contribution-ranked response includes nonnegative `node_gross_total`, calculated over all contributing constraints, and no longer includes `node_total`.
* [x] Structural (`rank=sf`) responses set `node_gross_total` to `null`.
* [x] The DetailCard displays a 0–100% gross-magnitude share instead of `contribution / node_total`, with the signed $/MWh value unchanged.
* [x] Focused API exposure tests pass (`14 passed`); frontend TypeScript no-emit check passes.
