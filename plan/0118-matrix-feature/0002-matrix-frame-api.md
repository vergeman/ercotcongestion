# 0002 - matrix-frame-api

Type: feat
Branch: `feat/0118-matrix-feature/0002-matrix-frame-api`
Source: `plan/0118-matrix-feature/sprint-matrix.md`

## Goal

* Serve a bounded, causally correct Matrix frame for a delivery timestamp.
* Return recovered shift factors, forecast `μ`, nullable ERCOT DAM `μ`, row metadata, and column metadata in one response.
* Make artifact provenance and missing-data states explicit.

## Dependency and merge position

* Start after `0001-explorer-shared-shell` is merged.
* This branch is backend-first: the UI should remain the Matrix placeholder.
* Merge when the endpoint is independently testable through OpenAPI/curl.

## Required context

* `forecast_sf_artifact` stores one dense compressed artifact per `(run_id, delivery_date)`.
* Each artifact contains the dense constraint × settlement-point `SF` matrix and hourly constraint expectations `E_mu`.
* `compute/sf/project.py::load_sf_mu` is the canonical decoder.
* The day's artifact is the causal source for the Matrix. Never answer a historical request with the latest map fit.
* Read-time node-driver code already implements the same `-μ × SF` arithmetic.
* Historical coverage is incomplete: some seeded forecast days have no artifact blob and must produce an explicit unavailable state.
* `/map/constraints/ranked` has useful daily predicted/realized ranking logic, but returns aggregates rather than the bounded dense rectangle required here.
* The artifact schema may not retain enough fit provenance for a strong historical label. Trace the daily producer before adding forward-only provenance fields; legacy provenance may remain `null`.

## Contract invariants

* Shift Factor value: `SF[c, sp]`.
* Contribution value: `-SF[c, sp] × μ[c, t]`; the browser performs this transparent display calculation.
* Forecast and ERCOT DAM modes use the same implied SF; only `μ` changes.
* Missing/not-yet-published DAM is `null`, never zero.
* Shadow price is row metadata, not a matrix mode.
* The server owns artifact selection, bounds, ordering, reconciliation, and availability.
* Row and column order is frozen for the delivery day; changing hour or `μ` source must not reorder the matrix.
* All initial hover/inspector metadata must be included to prevent later N+1 requests.
* Do not expose an official/ERCOT SF field. The matrix contains recovered implied SF only.

## Endpoint

```http
GET /matrix/frame
  ?interval_ts=2026-07-25T22:00:00Z
  &row_limit=30
  &column_limit=40
  &column_set=core
```

The response must include:

* `run_id`, `delivery_date`, and exact `interval_ts`;
* artifact availability and nullable fit-window provenance;
* `dam_status` (`pending`, `partial`, or `available`);
* explicit delivery-day ordering methods;
* ordered rows with stable constraint key/name, contingency, type, exact-hour forecast/DAM `μ`, daily rank, binding hours, and maximum `|SF|`;
* ordered columns with settlement-point name/type, load zone, and maximum `|SF|`; and
* a row-major dense `sf.values` array with explicit row/column counts.

Exact Pydantic field names can change during implementation, but these semantics must remain stable for downstream branches.

## Approach

* Work primarily in:
  * new `api/matrix.py`;
  * `api/main.py`;
  * API response models;
  * a small shared artifact-loading/query module extracted from existing serving code;
  * a forward-only migration only if provenance fields are added; and
  * `api/tests/test_matrix.py`.
* Resolve the forecast `run_id` and delivery date that actually cover the requested timestamp.
* Load through `compute/sf/project.py::load_sf_mu` and require the UTC timestamp to exist in the artifact's `E_mu` index.
* Return a documented unavailable response for a missing artifact; do not substitute a newer artifact or fabricate an empty matrix.
* Cache decoded immutable artifacts process-locally by `(run_id, delivery_date)` with bounded eviction and documented byte-size assumptions.
* Freeze row order by forecast daily absolute contribution over the day's `E_mu`; default to 30 rows and enforce a conservative maximum.
* For the frozen row universe, freeze core columns by maximum absolute SF with a deterministic settlement-point-name tie-break; default to 40 and enforce a maximum.
* Fetch exact-hour values from `ercot_dam_shadow_prices`.
* Reconcile constraint keys through one tested normalization function shared with the ranked endpoint where practical.
* Keep unmatched DAM rows as `ercot_dam_mu: null` and derive the aggregate status without coercion.
* If provenance is extended, record actual SF window/run when new artifacts are written and preserve readability of legacy artifacts.

## Tests

* [x] Artifact resolution selects the causal run/day.
* [x] UTC timestamps and the Central Time delivery-date boundary are correct.
* [x] Forecast `μ` comes from the exact artifact hour.
* [x] DAM `μ` matches normalized constraint keys at the exact hour.
* [x] Pending and partially matched DAM states retain `null`.
* [x] Ordering is deterministic and unchanged across hours.
* [x] Excessive row/column requests are rejected.
* [x] Dense values align with returned row/column labels.
* [x] Missing historical artifacts return the documented unavailable response.
* [x] Cache reuse never crosses run/day keys.
* [x] Legacy artifacts without provenance remain readable.

## Acceptance

* [x] One bounded request supplies every value and metadata field needed for the Matrix MVP at an hour.
* [x] The response can reproduce both forecast and ERCOT DAM `-SF × μ`.
* [x] No endpoint silently uses a future/latest SF fit for a historical request.
* [x] Missing DAM and missing artifact states are distinguishable.
* [x] Repeated requests do not repeatedly decode the same immutable NPZ.
* [x] API tests cover ordering, arithmetic inputs, availability, timestamp boundaries, and key reconciliation.
* [x] Existing map and forecast endpoints remain backward compatible.

## Merge boundary

Merge when the bounded API contract is complete and independently verified, while `/matrix` still displays the placeholder from branch 0001.
