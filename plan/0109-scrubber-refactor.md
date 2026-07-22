# 0109 - scrubber-refactor

Type: refactor
Branch: refactor/0109-scrubber-refactor

## Goal

* Remove the dead "binding" playback line from the Timeline sparkline — it is never populated.
* Rename the legacy product term `modeled congestion` → `congestion` in the scrubber.
* Remove the middle "N hrs" count from the scrubber range labels.

## Context

* The Playback Scrubber's `TimelineSparkline` draws two signals: a yellow `‖modeled congestion‖` area and a pink `binding` step line.
* `binding` is a retired product term; its series (`n_binding_lines`) is hard-coded to `null` in `App.tsx`, so the step line never renders.
* Verified: the sparkline's congestion signal is realized market congestion (`ercot.sps[].congestion`, Σ|·|), **not** forecast error — so the rename to `congestion` is accurate.
* Verified: `n_binding_lines` / `modeled_congestion_abs_total` are frontend-only. Nothing in `api/` or `compute/` serves them, so there is nothing to remove from API models/routes. (The API's `binding_hours` is a separate constraint-overview concept and is out of scope.)

## Approach

* Work in: `web/src/components/playback/TimelineSparkline.tsx`, `web/src/App.tsx`, `web/src/components/playback/PlaybackScrubber.tsx`

### Commit 1 — refactor: remove dead binding playback line

* `TimelineSparkline.tsx`: drop `n_binding_lines` from `SparkPoint`; remove `BINDING_COLOR`, `peakBinding`/`bindNorm`, the `stepPath` computation, the binding `<path>`, and the `binding` legend entry.
* `App.tsx`: remove `n_binding_lines: null` from the `sparkSeries` map.
* Do NOT touch: `api/` `binding_hours` (unrelated constraint-overview field).

### Commit 2 — refactor: rename "modeled congestion" → "congestion" in scrubber

* `TimelineSparkline.tsx`: legend label `‖modeled congestion‖` → `‖congestion‖`; rename `modeled_congestion_abs_total` → `congestion_abs_total` and `MC_ABS_COLOR` → `CONGESTION_COLOR`; update comments.
* `App.tsx`: update the `sparkSeries` map to the renamed field.
* Do NOT touch: `modeledCongestionColor` / `computeModeledCongestionStats` in `lib/colors.ts` (map-layer domain term, separate concern).

### Commit 3 — refactor: remove middle hours count from range labels

* `PlaybackScrubber.tsx`: remove the middle `<span>{timestamps.length} hrs</span>` from `scrubber__range-labels`, leaving the start/end timestamp labels.

## Acceptance

* [x] Sparkline renders only the congestion area; no pink binding line or `binding` legend entry remains.
* [x] No reference to `n_binding_lines` remains in `web/src/`.
* [x] Scrubber legend reads `‖congestion‖`; no user-facing `modeled congestion` string remains in the scrubber components.
* [x] The `N hrs` label no longer appears between the start/end range labels.
* [x] `web/` typechecks (no unused-symbol or missing-field errors).
