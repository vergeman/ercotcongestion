# 0161-0003 - Share operating defaults

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap/0003-shared-operating-defaults

## Goal

* Make the adopted map/forecast window, refit, and binding-admission defaults mechanically single-sourced.
* Retain semantic aliases where train and map terminology differ.

## Context

* `compute/sf/config.py` declares the adopted operating point, while `mu_model.py` repeats the matching `240` and `7` literals and `coverage_probe.py` repeats the matching `25` admission floor.
* CLI options must retain their current defaults and names.

## Approach

* Work in: `compute/sf/config.py`, `compute/mu/mu_model.py`, and direct default consumers.
* Import the SF operating values into `mu_model` and expose `DEFAULT_TRAIN_DAYS` / `DEFAULT_REFIT_DAYS` as aliases, if external callers use them.
* Expose `coverage_probe.DEFAULT_MIN_HOURS` as an alias of `sf.config.MIN_HOURS`; retain its probe-specific name for callers.
* Add a small regression test asserting the aliases and CLI parser defaults match `sf.config`.
* Do NOT merge model-specific constants such as panel lead-in, bind deadband, or memory spill policy into SF configuration.

## Acceptance

* [ ] No production 240-day, 7-day, or 25-hour operating default is duplicated outside the canonical configuration and intentional experiment configs.
* [ ] Existing CLI help/default behavior remains unchanged.
* [ ] Focused μ, SF, and weather-default tests pass.

## Suggested regression tests

* Assert the μ and coverage-probe aliases are object/value-equal to the SF configuration and that every affected argparse parser exposes the same numeric defaults as before.
* Keep an explicit test that the frozen `experiments/sf_out_of_window` defaults remain independent, so the cleanup cannot silently rewrite historical experiment settings.
