# 0161-0006 - Decompose μ model responsibilities

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap/0006-mu-model-seams

## Goal

* Reduce `mu_model.py` into focused modeling, walk scheduling, and artifact components.
* Preserve fitted predictions, fold boundaries, memory limits, and CLI behavior.

## Context

* `mu_model.py` combines head fitting, encodings, walks, chunks, spill management, artifact serialization, reporting, and CLI in one large module.
* Its test suite has broad direct monkeypatching, so compatibility façades are important.

## Approach

* Work in: `compute/mu/mu_model.py` and new `compute/mu/` modules.
* After the artifact-path plan, extract output serialization/chunk combination first; then extract head-fit/predict functions behind unchanged imports; defer walk orchestration and CLI to the final substep.
* Keep `walk_forward`, `predict_day`, and current public helper names callable from `mu_model.py` until downstream migration is complete.
* Establish fixed-panel/fixed-seed regression fixtures for predictions, weekly metrics, NPZ keys, and spill/non-spill equivalence.
* Do NOT change feature sets, model hyperparameters, fold allocation, seed handling, or memory spill lifetime.

## Acceptance

* [ ] Existing `test_mu_model.py` passes without expectation rewrites.
* [ ] Fixed inputs produce identical prediction tables and serialized artifacts.
* [ ] Spill and non-spill execution retain identical model output.

## Commit groups

* [x] `refactor(mu)`: extract prediction artifact serialization and chunk combination.
* [x] `refactor(mu)`: extract head fitting, encoding, and fold prediction helpers.
* [ ] `refactor(mu)`: extract walk scheduling and chunk orchestration behind compatibility exports.

## Suggested regression tests

* Add a small deterministic panel fixture and fixed seed, then compare `walk_forward` output pre/post extraction with exact frame/index equality, including fold/week boundaries and attrs such as novelty metadata.
* Compare `predict_day` outputs for each supported feature arm using the same panel, seed, and spill directory; require exact keys/order and numerical equality (or a documented machine-stable tolerance if the estimator changes representation).
* Generate `mu_preds.npz` and `mu_weekly.csv` from the fixed fixture before/after; compare decoded NPZ arrays, archive key set, CSV schema/order, and report text rather than relying only on successful reload.
* Exercise chunked and unchunked walks plus bind-matrix/panel spill modes; assert their combined predictions equal the non-spill single-process reference and that temporary spill files are removed.
