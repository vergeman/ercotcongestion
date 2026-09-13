# 0208 - legend-color-revision

Type: fix
Branch: fix/0208-legend-color-revision

## Goal

* Replace day-percentile map normalization with stable, dollar-denominated continuous color scales for congestion and LMP.
* Keep quiet playback ranges visually quiet while preserving smooth frame-to-frame color changes and useful high-price detail.
* Make the legend a dynamically cropped, faithful view of the fixed map scale and mark `$500/MWh` as Extreme Price.

## Context

* The current CT-delivery-day P90 congestion and P1/P99 LMP scales make a quiet `−$8…+$8` congestion range consume the darkest blue/red endpoints.
* Production DAM data (2024-04-15 through 2026-09-11) shows 81.6% of all congestion magnitudes and 79.7% of on-peak magnitudes below `$10`; 94% are below `$25`. On-peak LMP has meaningful density through `$300`, while `$500+` is rare (`~0.12%` on peak).
* Playback needs a continuous ramp, not discrete bucket changes: a fixed dollar value must retain its color across frames, while the compact legend should focus on the values visible in the current playback range.
* Existing map alarm halos and legend keys are percentile-relative (`3 × P90/P99`, with a congestion floor), so they must move to the same fixed `$500` contract.

## Approach

### Commit 1 — canonical continuous price transforms

* Work in: `web/src/lib/colors.ts`, plus every color-transform consumer (`web/src/components/map/GridMap.tsx`, `web/src/components/map/useMiniMapData.ts`, and `web/src/hooks/useExplorerSession.ts`).
* Entry point / primary change: replace `normalizeLmpFromStats` and `normalizeCongestion`'s percentile/rational-tail contracts with exported, canonical dollar-to-position transforms and their shared scale definitions.
* Define the LMP scale as an asymmetric blue → neutral → orange continuous ramp centered at `$25/MWh`, with interpolation controls at `−50, −20, 0, 10, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500`. Values below/above the endpoints clamp to the respective endpoint color.
* Define the congestion scale as a symmetric blue → neutral → red continuous ramp: an exactly neutral plateau for `−$10…+$10`, then signed controls at magnitudes `10, 25, 50, 75, 100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500`. Allocate the tail above `$100` progressively less color-space than the dense normal range, while retaining smooth interpolation at every dollar value.
* Keep `LmpStats` / `CongestionStats` only if needed to describe observed `min`, `max`, and count for a legend slice; remove percentile anchors from their semantic contract and stop using the loaded day to recolor nodes. Update actual, forecast, error, and mini-map callers so the same value gets the same normalized color everywhere.
* Replace `lmpAlarmThreshold`, `congestionAlarmThreshold`, `isLmpAlarm`, and `isCongestionAlarm` with a shared fixed `EXTREME_PRICE_THRESHOLD = 500`. Preserve the positive-only scarcity alarm for congestion; LMP at or above `$500` and positive congestion at or above `+$500` receive the existing halo.
* Do NOT change: palettes/theme colors, API payloads, playback fetching/caching, map tweening, selection/reach behavior, or DetailCard values.

### Commit 2 — faithful adaptive legend

* Work in: `web/src/components/map/Legend.tsx` and the scale helpers exported from `web/src/lib/colors.ts`.
* Entry point / primary change: replace the current endpoint labels (`±P90` for congestion and P1/median/P99 for LMP) with tick generation and bar-gradient slicing from the canonical scales.
* Derive the displayed legend domain from all values in the loaded playback range for the active metric, expand it to the nearest canonical anchor on both sides, and clamp it to the canonical scale endpoints. This changes only the displayed slice; it must never remap map colors.
* Build the gradient, histogram-bin positions, and tick positions through the same value-to-position transform used for fills. Select a readable subset of the active control points (always retain the neutral/reference value, active endpoints, and `$500` when relevant) so the 176px legend does not overlap labels.
* For a quiet congestion range such as `−$8…+$8`, render only the pale neutral-center slice with signed context ticks; do not display saturated endpoints. For higher LMP ranges, render the appropriate warm tail slice and its dense `$100–300` ticks.
* Replace the dynamic alarm copy with `Extreme Price ≥ +$500.00` for congestion and `Extreme Price ≥ $500.00` for LMP. Show the existing pulsing key only when the current data range contains a qualifying value; retain reduced-motion behavior.
* Keep the forecast-error palette override and labels, but use the canonical congestion magnitude transform so error, realized congestion, and forecast congestion have identical dollar spacing.
* Do NOT touch: legend overlay/type/aggregate controls, layout dimensions unrelated to ticks, or the map's existing halo animation implementation.

### Commit 3 — verification coverage

* Work in: focused color-scale tests if a lightweight existing frontend test entry point is available; otherwise add pure-function coverage only with the project-approved test runner, plus `web` build verification.
* Exercise the pure transforms at every fixed endpoint and just to either side: `±$8` congestion remains neutral, signs mirror beyond `±$10`, `$25` LMP is neutral, and interpolation is continuous at every listed control point.
* Cover invariance: the same LMP/congestion value gets the same normalized position regardless of other values in the playback day; `$500` triggers both fixed extreme classifiers and `$499.99` does not.
* Cover legend-domain selection: a quiet `−$8…+$8` congestion sample produces a neutral-centered slice, a `$100–300` LMP sample includes intermediate high-price ticks, and histogram placement uses the same positions as fills.
* Run `npm run lint` and `npm run build` in `web/`; manually inspect a quiet congestion playback, ordinary on-peak LMP playback, and a known `$500+` event in light and dark themes.

### Commit 4 — readable compact tick labels

* Treat the 176px legend as a fixed label budget: keep at most five labels and cull by estimated rendered width, not only by control-point distance.
* Place active endpoints first, then the neutral/reference and Extreme Price marker only when their labels fit without overlap; use remaining space for the most central useful anchors.
* Do not add a second tick row.

### Commit 5 — aligned histogram and zero orientation

* Bin histogram values against the displayed cropped dollar domain, so bars line up with the visible gradient rather than the hidden full scale.
* Include `$0` as an additional orientation candidate when it is in the displayed slice and its label fits the existing collision budget.

### Commit 6 — wider single-bar legend

* Keep one continuous legend bar and widen it to 280px so the collision-aware tick budget can show the cropped scale without overlap.

### Commit 7 — transformed legend geometry

* Position gradient stops, histogram bins, and ticks with the canonical color transform rather than raw dollar spacing for both LMP and congestion.
* Preserve the neutral congestion plateau with a linear fallback only when its displayed slice has no color-position span.

### Commit 8 — local extreme halos

* Keep `$500/MWh` as the fixed eligibility floor, but show LMP and positive-congestion halos only for the highest 1% of relevant values in the current frame.
* Rename the LMP legend key to `Extreme local price` to distinguish a local outlier from a systemwide high-price interval.

### Commit 9 — stable local-extreme key

* Reserve the local-extreme legend key when any loaded playback frame qualifies; dim it when the current frame has none, rather than changing the legend height.

## Acceptance

* [x] A congestion value in `−$10…+$10` is near-neutral on every playback day; it never becomes a saturated endpoint solely because the day's range is quiet.
* [x] LMP and congestion colors change smoothly during playback, and the same dollar value has the same color across realized, forecast, error (magnitude), and mini-map consumers.
* [x] The LMP ramp gives visibly finer continuous distinction through `$25–100` and `$100–300`; the congestion ramp concentrates distinguishable color changes below `$100` while preserving a smooth tail to `$500`.
* [x] `$500+` LMP and positive congestion receive the existing Extreme Price halo and fixed `$500.00` legend key; negative congestion remains signed blue without a scarcity halo.
* [x] The legend displays a cropped slice of the canonical ramp with non-overlapping meaningful ticks and histogram bins aligned to map-fill positions; it does not alter the map color contract.
* [x] `npm run lint` and `npm run build` pass in `web/`.
