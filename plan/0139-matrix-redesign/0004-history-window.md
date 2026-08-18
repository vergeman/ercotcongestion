# 0004 - history-window

Type: feat
Branch: `feat/0139-matrix-redesign/0004-history-window`
Source: `plan/0139-matrix-redesign/sprint-matrix-redesign.md`
Depends on: none. Optional — 0003 works on the existing 30-day series without it.

## Goal

Extend the trailing history series (currently 30 days) that backs the detail pane's sparkline /
whisker, IF it can be done without new precompute. Otherwise document the cap and the path.

## Context

* The trailing series is built in `api/analysis.py` by `_settled_mu_profile` (~line 509) and
  `_settled_node_profile` (~line 542), and surfaced on the Brief history fields
  (`settled_history`, `settled_history_p10..p90`).
* This is investigative: split out of 0003 so an uncertain data question never blocks the UI.

## Steps

1. Trace where the 30-day window is set in `_settled_mu_profile` / `_settled_node_profile` and
   whether the underlying settled table holds more than 30 days.
2. If the source has more history and the query is cheap to widen: parameterize the window
   (e.g. `window_days`, default the current value) and expose the longer series to the node
   endpoint `/analysis/node` (and/or a dedicated history call the detail pane uses).
3. If it needs new materialization/precompute: STOP. Write the finding + the extension path in
   this plan's PR and leave 30 days.
4. Do not change the Brief's default window/appearance — add capacity, don't alter existing calls.

## Do NOT touch

* `web/` code, `/matrix/frame`, the Brief's existing history rendering.

## Acceptance

* [ ] Either: a longer trailing window is available to the detail pane behind a param, with the
      Brief default unchanged — or: a written finding explains the cap and the extension path.
* [ ] No regression to the Brief history bars/whiskers.
