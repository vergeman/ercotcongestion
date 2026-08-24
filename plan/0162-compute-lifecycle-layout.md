# 0162 - Compute lifecycle layout

Type: refactor
Branch: refactor/0162-compute-lifecycle-layout

## Goal

* Separate production compute paths from reproducible experiments and external-data probes.
* Preserve every production job, artifact schema, CLI invocation, and forecast/map output.

## Context

* `compute/sf` and `compute/mu` mix model libraries with exploratory decision code.
* Deployed jobs call only the SF map, μ forecast, backfill, and grading paths.
* Outage crosswalk/exposure code is optional model capability, not merely probe code.

## Approach

* Work in: `compute/experiments/`, `compute/probes/`, `compute/sf/`, `compute/mu/`, and affected tests/docs/scripts.
* Create `compute/experiments/sf/` for `sweep_sf`, `coverage_probe`, and `r3_verdict`; retain `sf/grouping.py` beside `sf/eval.py` because the deployed evaluator imports it.
* Create `compute/probes/` for outage join/feed/crosswalk and RUC feasibility CLIs.
* Extract reusable outage crosswalk and exposure code into a production-neutral `compute/mu/outage/` package; make `features.py` import only that package.
* Remove legacy `compute.sf.*` / `compute.mu.*` experiment and probe paths after production callers have migrated to the lifecycle directories.
* Update experiment scripts and documentation to use the new paths; add a short production/experiments/probes index to `compute/README.md`.
* Do NOT move or rename deployed entry points: `compute.jobs.weekly_map`, `compute.jobs.daily_forecast`, `compute.jobs.backfill_nodal`, `compute.jobs.backfill_artifacts`, `compute.jobs.grade_day`, `compute.sf.geo_persist`, or `compute.sf.eval`.

## Acceptance

* [x] Production cron manifests and production entry-point module paths are unchanged.
* [x] 275 runnable SF/μ tests pass in the compute container.
* [ ] Job tests blocked by the container's missing `api.analysis` import pass once that test environment dependency is restored.
* [x] Production callers use only the new experiment, probe, and outage-library module paths; legacy shims are removed.
* [x] `daily_forecast` and `build_panel(..., with_outage=True)` import no experiment or probe module.

## Progress

* [x] Move SF decision CLIs; retain old executable paths and pass focused tests.
* [x] Move μ decision CLIs; retain old executable paths and pass focused tests.
* [x] Extract reusable outage crosswalk/exposure code from the probe CLIs; retain compatibility exports and pass focused tests.
* [x] Move feasibility probes; retain compatibility launchers and pass focused boundary tests.
* [x] Add the production/experiments/probes directory guide and migrate canonical command references.
* [x] Remove legacy experiment/probe launchers and outage-library re-export modules after production deployment verification.
