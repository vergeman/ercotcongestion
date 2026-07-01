# 0028 - matrix-metrics

Type: feat
Branch: feat/matrix-metrics

## Goal

* Add regime slicing to existing Spearman / Wasserstein / KS / PCA aggregates in `matrix_summary.json`.
* Add per-zone sign-agreement metric (global + per-regime).
* Add per-zone threshold-binding-count metric at τ ∈ {5, 20} $/MWh for model and ERCOT (global + per-regime).

## Context

* Phase 4 Tiers 3/4 and sign-agreement are the only metrics still missing from `matrix.py`.
* Regime label is already carried in each record's `hour` key as `"<regime>|<ts>"` — groupby, not new plumbing.
* ERCOT 2026 backfill is done; rerunning ercot + matrix stages will pick these up in one pass at N=120.

## Approach

* Work in: `compute/matrix.py`.
* Add helpers `_by_regime(rhos_or_series)`, `_sign_agreement(model_zone, ercot_zone)`, `_threshold_counts(zone_matrix, thresholds)`.
* Wire into the existing `by_ref_method.<ref>.cross_zones` block: emit `spearman.by_regime`, `distributional.by_regime`, `sign_agreement.{global,by_regime}`, `threshold_binding.{model,ercot}.{global,by_regime}`.
* Thresholds parameterized on the matrix CLI (`--binding-thresholds 5,20`, default `5,20`).
* Do NOT touch: congestion stage, clustering stage, or the `.npz` writer.

## Acceptance

* [ ] `matrix_summary.json:by_ref_method.hub_avg.cross_zones.spearman.by_regime` keyed by regime with mean/median ρ.
* [ ] `…cross_zones.sign_agreement.per_key.<zone>` gives fraction ∈ [0,1] globally and per regime.
* [ ] `…cross_zones.threshold_binding.model|ercot.per_key.<zone>` gives fraction of hours `|congestion| > τ` for each τ, globally and per regime.
* [ ] Full matrix stage rerun on `v1-120` completes in < 60 s and emits all new fields.
* [ ] Unit tests cover the three helpers on synthetic 8-zone × N-hour input.
