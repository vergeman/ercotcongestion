# B2 - validation-rewire

Type: feat
Branch: feat/0035-validation-rewire

## Goal

* Rewire `GET /api/validation` to correlate signed `modeled_congestion` against signed `basis` (Framing A) and expose a sign-agreement rate as a supplementary field (Framing C).
* Swap the endpoint's SQL to select the new columns, drop `abs()` from the Pearson pairs, and rewrite the docstring + router summary + warning strings around the new metric.
* Update `ScatterPoint` payloads to carry both signed `modeled_congestion` and signed `basis` (keeping `abs_basis` for backwards continuity of the magnitude view).

## Context

* Depends on B1 (`refactor/2b-schema-and-state`) for the renamed Pydantic models; depends on Sprint 2A Migration A for populated `modeled_congestion` rows in the window.
* This endpoint is the validation panel's headline number. The retired `fragility` metric produced ρ ≈ 0.008 vs `|basis|`; the sprint's thesis is that signed × signed correlation moves off zero.
* Framing decision locked (per sprint2b-plan.md §5): ship (A) signed × signed as the default, plus (C) sign-agreement rate as an additional response field. Skip (B) magnitude-only unless the scatter reads badly - can be re-added later without schema churn.
* Regime bucketing stays at the current congested/quiet split in the API; per-regime (`summer_peak`, `high_wind_west`, ...) stays in the frontend for now (open question §7.2 deferred).

## Approach

* Work in: `api/validation.py`, `api/models.py` (ScatterPoint + ValidationResponse fields only)
* `api/models.py`:
  * `ScatterPoint`: add `basis: float` (signed) alongside existing `abs_basis`. Keep `modeled_congestion: float` (already added in B1).
  * `ValidationResponse`: add `sign_agreement_overall: float | None` and `sign_agreement_congested: float | None` (fraction of bus-snapshots where `sign(modeled_congestion) == sign(basis)`, both non-zero). Nullable if window has no eligible rows.
* `api/validation.py`:
  * Rewrite the module + endpoint docstrings (lines 1-12) around "signed modeled_congestion vs signed basis; direction-preserving Pearson + sign-agreement rate."
  * Router summary line 74: `'Regime-bucketed correlation between modeled congestion and basis'`.
  * SQL line 112: `SELECT bs.modeled_congestion, bs.basis, ...`.
  * SQL line 121: `AND bs.modeled_congestion IS NOT NULL`.
  * Pearson pairs (lines 156-158): drop the `abs(r[1])` - use signed basis directly.
  * Warning string line 150: "fragility, basis" → "modeled_congestion, basis".
  * Add sign-agreement computation: count `sign(mc) == sign(basis)` over rows where both are non-zero, one value overall and one restricted to congested snapshots. Populate the two new `ValidationResponse` fields.
  * Scatter build (lines 186-193): update field names; emit signed `basis` and `abs_basis` on each point.
* Do NOT: bucket by regime in the API, add `/api/proximity_map`, add `binding_proximity` to the scatter, or touch `state.py` / models unrelated to validation.

## Acceptance

* [ ] `grep -rn "fragility" api/` returns zero hits after this branch lands.
* [ ] `GET /api/validation?start=&end=` returns ρ computed on signed `modeled_congestion` × signed `basis`; on a known-congested Sprint-0 window ρ visibly moves off the ~0.008 baseline (record the observed number in the PR; direction of movement is a finding, not a gate).
* [ ] Response carries `sign_agreement_overall` and `sign_agreement_congested` as floats in [0, 1] (or null if no eligible rows).
* [ ] `ScatterPoint` records include signed `modeled_congestion`, signed `basis`, and `abs_basis`.
* [ ] Endpoint returns 200 against a DB with Migration A applied and at least one recomputed window; `IS NOT NULL` filter tolerates partial coverage.
* [ ] Docstring + router summary + warning strings no longer mention `fragility`.
