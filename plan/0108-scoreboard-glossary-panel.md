# 0108 - scoreboard-glossary-panel

Type: feat
Branch: feat/0108-scoreboard-glossary-panel

## Goal

* Add a right-rail glossary panel to `ScoreboardPage` explaining the model, sources, and metrics.
* Add custom hover/focus tooltips and reorganize the header meta.

## Context

* Work is scoped to `web/src/pages/ScoreboardPage.tsx`.
* Local Node 18 cannot build; verify changes in the browser.

## Approach

* Work in: `web/src/pages/ScoreboardPage.tsx`

### Glossary rail

* Add a right-side glossary `<aside>` beside the board; split page into main + rail with the map's proportional split (`flex 5` / `flex 2`, `--panel-w` floor), stacking below 900px.
* Give the rail its own scroll so the graph stays static while the notes scroll.
* Section blocks with larger headers + separator rules.
* "What the model predicts" block: congestion identity `congestion = −Σ SF · μ`; μ / SF inline definitions; two-head split `E[μ] = P(bind) · E[μ | bind]`; Head 1 / Head 2 with their regressors (ridge for SF, gradient-boosted classifier for P(bind), gradient-boosted regressor on log(μ) for E[μ|bind]); worked example with labeled heads and spelled-out arithmetic.
* "Model Comparison Graph" block: Model / Persistence / Climatology / Oracle definitions; climatology worked example.
* "Pre / Post-RTC+B" block.
* Scoring block: Top-Decile Hit, Rank ρ, Sign Agreement.
* Magnitude block: Pooled R², MAE (Mean Absolute Error).

### Tooltips

* Add a `Term` component: dotted-underline trigger + styled hover/focus popover (accepts rich JSX content).
* Apply to: binding, heads, Pooled; header labels Backtest run, Window, Hours.
* Fix the graph hover tooltip to be theme-aware (`--bg-glass`, not hardcoded dark).
* Bump tooltip and rail font sizes.

### Header

* Order: Backtest run · Window (days) · Hours (weeks + regime select).
* Rich Hours tooltip (net-load quintile bullets Q1–Q5).
* Right-anchor header popovers; space the select from the week count.

### Metrics

* Reorder screening metrics: Rank ρ, Sign Agreement, Top-Decile Hit last — across screening buttons, default metric, group toggle, headline tiles, live tiles.

### Misc

* Remove the legend note under the graph ("screening currency leads…").

## Acceptance

* [ ] Glossary rail renders beside the board and scrolls independently.
* [ ] All defined terms show the custom popover on hover and focus.
* [ ] Graph hover tooltip follows the light/dark theme toggle.
* [ ] Header shows Backtest run · Window · Hours in that order.
* [ ] Metric order leads with Rank ρ / Sign Agreement everywhere.
