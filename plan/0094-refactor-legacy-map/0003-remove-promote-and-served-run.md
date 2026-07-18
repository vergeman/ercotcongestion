# 0094-0003 - remove compute.promote + the served_run_dir serving model

Type: refactor
Branch: refactor/0094-0003-remove-promote-and-served-run

## Goal

* Delete `compute/promote.py` (the scorecard-cell / `current`-symlink promote CLI) and
  the `served_run_dir` serving model, now that no endpoint reads it.
* Remove the ops wiring: `SERVED_RUN_DIR`, the `current` symlink, and the promote
  shell-pod invocation.

## Context

* After `0001` (meta gone) and `0002` (Congestion DB-sourced), nothing in `api/` reads
  `settings.served_run_dir`.
* `compute/promote.py` flips per-cell symlinks (`scorecard.json`, `scorecard_series.npz`,
  `cluster_labels.npz`, `mapping_correlation_summary.json`) and the top-level `current`
  link — all legacy-map artifacts. Its bp/IBP step was already removed in `0093-0003`.
* Ops references: `ops/deploy/base/configmap.yml` (`SERVED_RUN_DIR`) and
  `ops/deploy/jobs/compute_shell_pod.yml.template` (runs promote / references the
  matrix/mapping build).

## Approach

* Work in: `compute/promote.py` (delete), `shared/settings.py`, `api/config.py` /
  `api/db.py` if they surface the setting, `ops/deploy/base/configmap.yml`,
  `ops/deploy/jobs/compute_shell_pod.yml.template`.
* Delete `compute/promote.py`.
* Remove `served_run_dir` from `shared/settings.py` and any re-export; confirm no
  remaining importer (post-0001/0002 there are none in `api/`).
* Ops: drop `SERVED_RUN_DIR` from the configmap and the promote/scorecard steps from the
  shell-pod template; retire the `current` symlink convention in the runs volume docs.
* Do NOT touch: `compute/legacy/` itself (that is `0004`); `compute/sf`, `compute/mu`,
  and the map/forecast cronjobs (they do not use `served_run_dir`).

## Acceptance

* [ ] `compute/promote.py` gone; `grep -rn "served_run_dir\|compute.promote" --include=*.py .`
  returns nothing outside `compute/legacy/`.
* [ ] `grep -rn "SERVED_RUN_DIR\|/current" ops/` returns nothing live.
* [ ] API boots without `SERVED_RUN_DIR` set; `/map/*`, `/topology`,
  `/ercot_spp_range`, `/ercot_state_range` all serve.
* [ ] `pytest` green.
