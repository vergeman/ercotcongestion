# 0174 - refactor propagate window

Type: refactor
Branch: refactor/0174-refactor-propagate-window

## Goal

* Split `propagate_window` into small helpers for SF selection, score-window alignment, and projection.
* Preserve its historical and forward forecast results exactly.

## Context

* The function mixes rolling fit selection, persisted-map alignment, coverage accounting, projection, and scoring.
* `daily_forecast` uses forward mode; the historical backfill uses scored mode.

## Approach

* Work in: `compute/projection/propagate.py` and its focused tests.
* Extract private helpers while retaining the public function signature and return contract.
* Cover the persisted-SF alignment path and run projection/forecast tests.
* Do NOT change projection math, score metrics, SF-fit parameters, or database behavior.

## Acceptance

* [x] `propagate_window` coordinates clear single-purpose helpers.
* [x] Forward and scored modes retain their existing output contract.
* [x] Focused projection and forecast tests pass.
