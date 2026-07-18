# 0097 - map-ui-fixes

Type: fix
Branch: fix/0097-map-ui-fixes

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add an "off" state to the palette so the map can show no congestion/LMP fill (overlay-only focus).
* Fix the constraints overlay button so it actually toggles the SF overlay.
* Generalize the `DetailCard` to both panes so a click on the actual/ERCOT side opens a detail card too, not only the prediction side.
* Add a sticky highlight on the clicked node so the active selection stays visible until another node is selected or cleared.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* Current state: palette has no off value; the constraints overlay button is non-functional; only the prediction pane wires a `DetailCard`; there is no persistent indication of which node is active after a click.
* These are the visibility-gating fixes — they let the map layout decisions in 0098 be judged by looking rather than guessing, and the palette-off + overlay-toggle work is reused by 0098's basis/dual defaults.
* Pure front-end; no API or compute change.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `web/src/components/map/{GridMap,DetailCard,Legend,OverviewOverlay}.tsx`, `web/src/App.tsx`.
* Palette off: add an `off` value to the palette/view state; when set, `GridMap` renders no SP fill while the SF overlay remains independently toggleable.
* Overlay button: trace the button → state → `OverviewOverlay` visibility path and fix the broken wiring so the overlay shows/hides on click.
* DetailCard per side: lift the click-to-detail handling so both `side="prediction"` and `side="actual"` panes open a `DetailCard` for their own click; keep each card scoped to its pane's data.
* Sticky highlight: hold the selected `sp_id` in state, render a distinct persistent style on it (independent of hover), and clear on empty-map click or a clear affordance.
* Do NOT touch: API, compute, or the scoreboard/side panel.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] Palette can be set to off: no congestion/LMP fill renders, and the SF overlay is still independently toggleable.
* [ ] The constraints overlay button visibly toggles the overlay on and off.
* [ ] Clicking a node on either pane opens a `DetailCard` for that pane.
* [ ] A clicked node stays visibly highlighted until a different node is selected or the selection is cleared.
