# 0133a - refit-boundaries-dst-drift

Type: fix
Branch: fix/0133a-refit-boundaries-dst-drift

## Goal

* Fix `mu_model.refit_boundaries` so its weekly refit grid stays on true CT
  midnight across a DST transition instead of silently drifting an hour after
  crossing one.

## Context

* Found while auditing 0133's memory-chunked jobs for CT-block safety.
* Two independent traps, both silent, both needed for the fix:
  1. `refit_boundaries` converts `score_from`/`anchor` to the panel's UTC tz
     *before* calling `date_range` — locks the grid onto UTC's wall clock
     instead of the origin's.
  2. `freq=pd.Timedelta(days=N)` is a fixed physical duration (absolute-time,
     DST-oblivious) on the production pandas (3.0.3) — only `DateOffset`/the
     `"ND"` string form preserves wall-clock time across a transition. (An
     initial pandas 2.3.3 host check showed `Timedelta` freq as wall-clock-safe
     — that was the wrong pandas version; verify against the actual runtime,
     not the host, next time.)
* Latent, not currently triggered by `daily_forecast.py` / `backfill_artifacts.py`
  — neither calls `refit_boundaries`/`score_chunks` at all. Only the offline
  backtest CLI (`mu_model.py`'s `walk_forward` / `walk_forward_chunked` /
  `--chunk-weeks`) is affected, and only once `--score-from` is CT-anchored
  (0133's Commit 2 fix).

## Approach

* Work in: `compute/mu/mu_model.py`
* Entry points: `refit_boundaries`, `score_chunks`
* Generate the grid in `score_from`'s (or `anchor`'s) own tz using a
  `DateOffset` step, then convert the resulting `DatetimeIndex` to the panel's
  tz — never convert the origin first, never step with a bare `Timedelta`.
* Do NOT touch: `sf/eval.py`, `sf/rolling.py`, `weekly_map.py` — already
  UTC-native throughout (origin always derived from the UTC panel itself), so
  `Timedelta`-freq stepping there is harmless (UTC has no DST to drift
  against); verified unaffected by this class of bug.

## Acceptance

* [x] A `refit_boundaries` grid spanning a DST transition stays at CT midnight
      on both sides, for a CT-tz `score_from`
      (`test_refit_grid_stays_on_ct_midnight_across_dst`).
* [x] `score_chunks` likewise
      (`test_score_chunks_stay_on_ct_midnight_across_dst`).
* [x] Existing UTC-`score_from` callers/tests unchanged (byte-identical grid —
      full `test_mu_model.py` suite green, 34/34).
