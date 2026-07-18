# 0098 - map-basis-dual-view

Type: feat
Branch: feat/0098-map-basis-dual-view

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add a single **basis** map view (predicted − market congestion) as the default landing view, with the SF overlay on.
* Add a **dual compare** view (prediction | ERCOT side by side) reachable by toggle, with the SF overlay default-off but still toggleable.
* Model view-mode (`basis` | `dual`) and palette (`congestion` | `lmp` | `off`) as two orthogonal axes in state.
* Have the `DetailCard` always carry the predicted / market / basis decomposition on click, in any view.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* Depends on 0096 (forecast data present on the left) and 0097 (palette-off, per-side `DetailCard`, working overlay toggle).
* The basis is the product thesis rendered directly ("where we disagree with the market") and the SF overlay is its mechanism (the constraints that generate the disagreement) — so SF pairs with basis and is default-on there; on dual it is a per-pane explainer, default-off not absent.
* Basis is congestion-only: LMP-basis collapses to congestion-basis *exactly*, because both panes subtract the same `dam_system_lambda` (prediction side per 0096; market side per `api/ercot_state.py`), so λ cancels in the difference and no separate LMP-basis mode is needed. Basis default aligns the landing screen with what the scoreboard grades.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `web/src/App.tsx` (state model), `web/src/components/map/{GridMap,CompareMap,DetailCard,Legend}.tsx`.
* Add a `viewMode` axis (`basis` | `dual`) independent of the existing palette axis; default `basis`.
* Basis view: single `GridMap` colored by per-SP (predicted − market) congestion on a diverging palette centered at 0; SF overlay default-on. Compute the difference client-side from the two per-SP series already in state (no new API).
* Dual view: the existing `CompareMap` (prediction left, ERCOT right); SF overlay default-off, toggleable (reuse the 0097 overlay toggle).
* `DetailCard`: always include predicted / market / basis for the clicked SP, so basis-default never hides raw magnitude.
* Keep prediction on the left in dual (product subject; one-line to swap if reversed later).
* Do NOT touch: API or compute — basis is derived on the client from data 0096 already serves.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] App lands on the single basis view with the SF overlay on.
* [x] A toggle switches to dual compare; the SF overlay is off there by default and still toggleable.
* [x] Basis coloring equals predicted − market congestion on a diverging palette centered at 0.
* [x] `viewMode` and palette are independent — palette off/congestion/lmp behaves correctly in dual, and basis stays congestion-based regardless of palette.
* [x] The `DetailCard` shows predicted / market / basis in both views.
