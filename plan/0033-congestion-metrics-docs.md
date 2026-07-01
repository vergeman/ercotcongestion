# B5 - congestion-metrics-docs

Type: docs
Branch: docs/congestion-metrics

## Goal

* Replace `fragility` prose in `compute/**/*.md` with `modeled_congestion` + `binding_proximity` definitions, formulas, and sign convention.
* Update the stale one-liner comment in `preprocess/verify.py` (~line 112-114).
* Ship after B4 so docs describe what's actually in the DB.

## Context

* Scope is backend docs only. API/frontend docs land with 2B / 2C.
* Sign convention text must quote the empirically-verified convention committed in B1's `verify_sign_convention.py`, not restated from documentation.

## Approach

* Work in: `compute/*.md`, `preprocess/verify.py`
* Files to edit:
  * `compute/README.md` - replace "fragility" section with the two new metrics: formula, sign convention (with brief note on how it was verified), units.
  * `compute/snapshot.md` - update result-dict schema section (drop `fragility`, add `modeled_congestion`, `binding_proximity`; add five new meta keys).
  * `compute/rank.md` - reword the "West/Houston rank" narrative to reference modeled congestion; math unchanged.
  * `compute/Basis.md` - update prose mentions of `fragility`.
  * `compute/N1.md`, `compute/opf.md` - grep and reword `fragility` mentions.
  * `preprocess/verify.py` line ~112-114 - delete stale comment `"fragility = PTDF x shadow_price / headroom"`.
* Do NOT touch: API docs, frontend docs, `compute/*.py` (all covered by B1).
* Do NOT reintroduce a "fragility" definition anywhere; the term is retired.

## Acceptance

* [ ] `rg -l fragility compute/` returns no matches (docs or code).
* [ ] `compute/README.md` documents both metrics with formula + sign convention + units.
* [ ] `compute/snapshot.md` result-dict schema section lists the new result + meta keys and no old ones.
* [ ] `preprocess/verify.py` stale comment removed.
