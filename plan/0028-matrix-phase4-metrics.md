# 0028 - matrix-metrics

Type: feat
Branch: feat/matrix-metrics

## Goal

* Add regime slicing to existing Spearman / Wasserstein / KS / PCA aggregates in `matrix_summary.json`.
* Add per-zone sign-agreement metric (global + per-regime).
* Add per-zone threshold-binding-count metric at τ ∈ {5, 20} $/MWh for model and ERCOT (global + per-regime).
* Add per-zone diurnal + DOW temporal profiles (Tier 3) with Pearson corr between model and ERCOT bucket means (global + per-regime).

## Context

* Phase 4 Tiers 3/4 and sign-agreement are the only metrics still missing from `matrix.py`.
* Regime label is already carried in each record's `hour` key as `"<regime>|<ts>"` — groupby, not new plumbing.
* Timestamp is the tail of that same key (`"<regime>|<iso_ts>"`) — parsed for hour-of-day (UTC) and day-of-week without new inputs.
* ERCOT 2026 backfill is done; rerunning ercot + matrix stages will pick these up in one pass at N=120.

## Approach

* Work in: `compute/matrix.py`.
* Add helpers `_by_regime(rhos_or_series)`, `_sign_agreement(model_zone, ercot_zone)`, `_threshold_counts(zone_matrix, thresholds)`, `_temporal(model_zone, ercot_zone, keys)` + `_bucket_profile` + `_ts_of`.
* Wire into the existing `by_ref_method.<ref>.cross_zones` block: emit `spearman.by_regime`, `distributional.by_regime`, `sign_agreement.{global,by_regime}`, `threshold_binding.{model,ercot}.{global,by_regime}`, `temporal.{global,by_regime}.{diurnal,dow}`.
* Thresholds parameterized on the matrix CLI (`--binding-thresholds 5,20`, default `5,20`).
* Temporal buckets: hour-of-day 0–23 UTC, day-of-week 0=Mon; per-bucket sample counts emitted alongside means so consumers can see coverage limits at N=120 (sample-selection favors regime-characteristic hours; per-regime diurnal is thin).
* Do NOT touch: congestion stage, clustering stage, or the `.npz` writer.

## Acceptance

* [x] `matrix_summary.json:by_ref_method.hub_avg.cross_zones.spearman.by_regime` keyed by regime with mean/median ρ.
* [x] `…cross_zones.sign_agreement.per_key.<zone>` gives fraction ∈ [0,1] globally and per regime.
* [x] `…cross_zones.threshold_binding.model|ercot.per_key.<zone>` gives fraction of hours `|congestion| > τ` for each τ, globally and per regime.
* [x] `…cross_zones.temporal.{global,by_regime}.diurnal.per_key.<zone>` emits model + ercot bucket means (24 HoD buckets) and Pearson `corr`; same shape for `.dow` (7 buckets); `n_per_bucket` reported for coverage disclosure.
* [x] Full matrix stage rerun on `v1-120` completes in < 60 s and emits all new fields.
* [x] Unit tests cover the sign-agreement, threshold-count, and regime-split helpers on synthetic 8-zone × N-hour input. (Temporal helper exercised via integration rerun; no synthetic unit test — add alongside Sprint 2 work if needed.)
