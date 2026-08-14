# 0130 - map-view-data-controls

Type: feat
Branch: feat/0130-map-view-data-controls

## Goal

* Replace the map header controls with a four-chip segmented `View` control —
  `Forecast | Market | Compare | Error`, exactly one active — plus
  `Data: Congestion | Price (LMP)`. Compare = the dual forecast | market split;
  Error = the forecast − market error single. Chip labels are provisional
  (revisit copy later); the mechanics are settled.
* Build the two missing single views (Forecast-only, Market-only); Compare keeps the
  existing dual split; Error keeps the existing error single.
* Move the constraints toggle out of the header into a small per-pane floating legend,
  shown only on panes rendering forecast data; drop the palette `Off` option.
* Render implied forecast LMP (`p50 + λ`) on unsettled days using a persistence λ curve
  (the most recent settled day's 24 hourly values), labeled as indicative.
* Label every pane with what it shows (view + data + timestamp) — current labeling is
  weak and this is a first-class deliverable, not polish.

## Context

* Today `viewMode` is `forecastError | dual` and `palette` is `congestion | lmp | off`;
  single Forecast and single Market views do not exist, and forecast-error is the
  default landing. This re-factors the same map machinery under a cleaner state space.
* Validity rules, each with a one-line tooltip justification:
  * Market, Compare, and Error require settled data → disabled pre-market
    ("Available after market posts"), one contiguous span of the control graying out.
    Pre-market leaves Forecast × Congestion/LMP.
  * Error locks Data to Congestion (both sides share the market λ, so price error ≡
    congestion error, `api/types.ts:126`); leaving Error restores the prior data
    selection.
  * The View control is a single mutually exclusive selection — no compare flag, no
    secondary active states. Leaving Compare for Forecast or Market is ordinary chip
    selection.
* Persistence λ is a display convention, not a model: no parameters, nothing to grade.
  The scoreboard, grade panel, and error view stay congestion-only — λ̂ must never
  enter any graded or error surface.
* Bare `/map` lands on single Forecast × Congestion. The layman "watch price move"
  entry (Market × LMP, autoplay) is selected by parameterized links — that is 0131's
  job, not this branch's. Buttons only here; no URL read/write.

## Approach

* Work in: `web/src/components/layout/Header.tsx`, `web/src/workspaces/MapWorkspace.tsx`,
  `web/src/api/types.ts`, and the GridMap legend.
* Replace `ViewMode`/`Palette` with two typed axes:
  `view: "forecast" | "market" | "compare" | "error"` and
  `data: "congestion" | "lmp"`. Keep the state factored so 0131 can serialize it
  later unchanged.
* Header renders the segmented View control and the Data group; compute availability
  from whether settled data exists in the loaded window; disabled chips get a
  Tooltip, they do not hide.
* Single Forecast / single Market: reuse the existing left/right pane components
  full-width (the error single already shows the pattern at `forecast-error-single`).
* Persistence λ: fill server-side — add a query so `/forecast_range` returns
  `system_lambda` on unsettled hours from the latest settled day's curve by
  hour-ending, plus a provenance flag (e.g. `lambda_source: "settled" | "persisted"`)
  per interval. Legend and hover mark the price level as indicative on persisted
  hours. Verify first what `/forecast_range` returns for `system_lambda` today.
* Per-pane legend: title (what's shown + timestamp), color scale, and — on forecast
  panes only — the constraints overlay checkbox. Market panes get no constraints
  control. In Compare, each pane carries its own legend.
* Mobile stays forced-single; it follows the active data selection with view resolved
  to Forecast.
* Do NOT touch: grading/error math, the scrubber, API endpoints, URL params
  (`useTimeCursor`, `mapLinks`).

## Acceptance

* [ ] Header shows the segmented View control and Data group; every valid
      (view, data) combination renders; invalid chips are disabled with a tooltip,
      per the rules above.
* [ ] Pre-market: Market / Compare / Error disabled with "Available after market
      posts"; Forecast × Congestion and Forecast × LMP (persisted λ) work.
* [ ] Selecting Error locks Data to Congestion (tooltip explains); leaving Error
      restores the prior data selection.
* [ ] Constraints toggle appears only in forecast-pane legends; header has no
      constraints or `Off` control.
* [ ] Unsettled-hour LMP renders with the persisted λ curve and an "indicative level"
      marker in legend/hover; settled hours use settled λ with no marker;
      `lambda_source` is present per interval in the payload.
* [ ] Bare `/map` lands on single Forecast × Congestion; every pane is labeled with
      view + data + timestamp.
* [ ] Scoreboard, grade panel, and error view outputs are byte-identical to before
      (λ̂ touches display only).
* [ ] `tsc --noEmit -p web/tsconfig.app.json` clean.

## Task note

* 0131 (map views and link) serializes this state as the Map URL contract
  (`view=forecast|market|compare|error`, `data=congestion|lmp`) and targets the
  hero link at Market × LMP + autoplay, canonicalized to Forecast × LMP
  pre-settlement. It depends on this plan; keep the state factored exactly as above.
