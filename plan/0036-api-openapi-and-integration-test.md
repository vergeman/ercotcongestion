# B3 - api-openapi-and-integration-test

Type: chore
Branch: chore/0036-openapi-and-integration-test

## Goal

* Confirm the FastAPI-generated OpenAPI spec reflects the renamed fields after B1 + B2, and regenerate any checked-in snapshot.
* Add one integration test that boots the API against a DB with Migration A applied and hits `/api/state`, `/api/state_range`, `/api/validation` end-to-end.
* Capture the observed `/api/validation` ρ + sign-agreement numbers on the Sprint-0 window into the sprint report so B2's headline claim is auditable.

## Context

* Depends on B1 + B2 landed and Sprint 2A Migration A applied on the test DB.
* Post-merge smoke test; safe to fold into B2's PR if reviewer prefers a single commit.
* Not part of the Migration B (drop `fragility*` columns) gate - that ships only after 2B AND 2C are green in deploy.

## Approach

* Work in: `api/tests/`, `plan/` (results append)
* OpenAPI:
  * `grep -rn "openapi" api/tests/` - if there is a checked-in snapshot, regenerate it after B1 + B2.
  * Otherwise: hit `/openapi.json` locally (or in a test) and assert that `BusState`, `SnapshotMeta`, `ScatterPoint`, and `ValidationResponse` list the new field names and none of the retired ones.
* Integration test (new file or extension of `api/tests/test_state.py`):
  * Boot the API against a DB with Migration A applied and at least one recomputed snapshot in the Sprint-0 sample window.
  * Hit `GET /api/state?t=<sample-ts>`, `GET /api/state_range?start=&end=` (small window), and `GET /api/validation?start=&end=`.
  * Assert 200 + expected shape (fields present; no `fragility` key anywhere).
  * Assert `/api/validation` tolerates partial `modeled_congestion` coverage - insert one row with NULL to confirm `IS NOT NULL` filter path.
* Sprint report:
  * Append a short "2B results" block to `plan/sprint2b-plan.md` (or a new `docs/sprint2b-results.md` if the plan file should stay pristine): observed ρ, sign-agreement overall + congested, sample window used, timestamp.
* Do NOT: run Migration B, touch frontend, or modify any 2A code paths.

## Acceptance

* [x] OpenAPI assertion test (`test_openapi.py`) confirms renamed fields present, no `fragility*`.
* [x] Integration test (`test_integration.py`, gated by `RUN_INTEGRATION=1`) hits `/state`, `/state_range`, `/validation` against live DB — 4/4 pass.
* [x] NULL `modeled_congestion` probe row inserted + cleaned up; `IS NOT NULL` filter excludes it without error.
* [x] Sprint report §8 appended to `sprint2b-plan.md` (ρ=0.756, sign_agreement=0.575, window, south-zone finding).
* [x] `grep -rn "fragility" api/` — only the two `not in` regression guards remain.

Aside (pre-existing): tests hit `/api/state` while routers mount at `/state`. Fixed here so the suite actually runs — frontend calls `/state` (no prefix), so tests now match production.
