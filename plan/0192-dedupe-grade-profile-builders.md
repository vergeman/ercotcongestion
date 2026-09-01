# 0192 - dedupe-grade-profile-builders

Type: refactor
Branch: refactor/0192-dedupe-grade-profile-builders

## Goal

* Make `api/services/analysis/panels.py` import the profile/grade builders from `compute/analysis/brief_grade.py` instead of re-implementing them.
* Remove the duplicated builder copies from `panels.py` with no change to API responses.
* Land before 0189 so its comparison-contract edits touch one construction, not two.

## Context

* The profile-building layer exists twice: `brief_grade.py` (feeds the `materialize_brief_grade` job) and `panels.py` (feeds the live API). `panels.py` already imports the grading entrypoints from `brief_grade` but re-implements everything under them.
* The two copies have drifted: `brief_grade` has one `_windowed_profiles(cur, dd, days, *, nodes)`; `panels` split it into `_windowed_mu_profiles` + `_windowed_node_profiles`. Same SQL, two maintenance sites.
* 0189 rewrites the comparison contracts inside `brief_grade.py`; with the duplication standing, a construction change must be mirrored into `panels` by hand or silently diverges.

## Duplicated builders

`settled_mu_profile`, `forecast_mu_profile`, `_forecast_node_profile`, `_settled_node_profile`, `_ordinal_profile`, `_windowed_profiles` (paired against `_windowed_mu_profiles`/`_windowed_node_profiles`), `_trailing_settled_average`, `_grade_vocabulary`.

## Approach

* Work in: `api/services/analysis/panels.py`, `compute/analysis/brief_grade.py`, `api/tests/test_analysis.py`, `compute/analysis/tests/test_brief_grade.py`.
* Treat `brief_grade.py` as the single owner. Where a builder is private (`_`-prefixed) but now needs cross-module import, promote it to a public name; keep the signature.
* Delete the `panels.py` copies and import from `brief_grade`. Reconcile the windowed-profile split: `panels` calls `brief_grade._windowed_profiles(..., nodes=True/False)` at its two call sites; drop `_windowed_mu_profiles` and `_windowed_node_profiles`. Preserve the tuple-row cursor already in `brief_grade`.
* Update tests that monkeypatch these by module attribute to patch `brief_grade.*` (the api tests already patch `brief_grade._forecast_node_profile`, so follow that pattern).
* Add one line to the 0189 plan noting this consolidation, so its "do not relocate code" constraint (aimed at the comparison enum) is not read as forbidding this builder move.
* Do NOT touch: the grading entrypoints (`grade_constraint_profiles`, `grade_node_profiles`, `serialize_grade_half`, `COMPARISONS`) — already shared; the `hero_*`, `phrases`, `metadata`, `families` modules; the SF-math rename of `compute/analysis/brief.py` (separate, out of scope).

## Acceptance

* [x] The eight builders exist only in `brief_grade.py`; `panels.py` imports them.
* [x] `/analysis/*` and `/analysis/brief` responses are unchanged.
* [x] One `windowed_profiles(nodes=...)` serves both the mu and node call sites.
* [x] `api/tests/test_analysis.py` and `compute/analysis/tests/test_brief_grade.py` pass with patches pointed at `brief_grade`.
* [x] 0189 carries a note acknowledging this builder consolidation.
