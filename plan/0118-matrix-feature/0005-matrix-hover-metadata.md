# 0005 - matrix-hover-metadata

Type: feat
Branch: `feat/0118-matrix-feature/0005-matrix-hover-metadata`
Source: `plan/0118-matrix-feature/sprint-matrix.md`

## Goal

* Add fast hover/focus explanations for cells, row headers, and column headers.
* Keep the grid compact while exposing enough metadata to orient an unfamiliar user.
* Reuse the loaded frame; never fetch on hover.

## Dependency and merge position

* Start after `0004-matrix-selection-inspector` is merged.
* Tooltips must share calculations and formatting with the core matrix and inspector.
* Merge when the bounded matrix is understandable without opening the inspector for every value.

## Required hover contract

### Cell

Show:

* constraint and contingency;
* settlement point;
* implied SF;
* Forecast `μ` and contribution;
* ERCOT DAM `μ` and contribution.

Unavailable DAM must say “Not published” or “No matched DAM value,” never `$0`.

### Row header

Show:

* full constraint and contingency name;
* constraint type;
* daily contribution rank;
* selected-hour Forecast/DAM `μ`;
* binding or active-hour count; and
* maximum `|SF|`.

### Column header

Show:

* full settlement-point name;
* SP type and load zone when available;
* maximum `|SF|` in the displayed row universe; and
* visible-row contribution sum for the selected hour/source.

## Approach

* Reuse the project's unified tooltip primitives and visual language.
* Support pointer hover and keyboard focus with equivalent content.
* Use one tooltip controller or delegated event model rather than hundreds of independent portal/state instances.
* Keep tooltips within the viewport around sticky headers and scroll edges.
* Use the exact arithmetic/formatting helpers used by cells and the inspector.
* Treat absent metadata as unknown; do not infer zone or constraint type solely for presentation.
* Profile the default 30 × 40 rectangle with tooltips enabled.

## Invariants and out of scope

* Hover/focus never changes selection, ordering, playback state, filters, or matrix universe.
* Hover/focus makes no network request.
* Recovered implied SF must not be presented as an official ERCOT factor.
* Search, filters, pins, all-data virtualization, and new metadata queries remain out of scope.

## Acceptance

* [ ] Every focusable row header, column header, and cell exposes the intended tooltip.
* [ ] Pointer and keyboard users receive equivalent information.
* [ ] Hovering changes no selection, order, playback, or filter state.
* [ ] No network request occurs because of hover/focus.
* [ ] Tooltip values agree with the matrix cell and persistent inspector.
* [ ] Missing DAM values have accurate unavailable labels rather than zeroes.
* [ ] Tooltips remain readable at matrix edges and around sticky headers.
* [ ] Default-rectangle interaction remains performant.

## Merge boundary

Merge when all three target types provide consistent, accessible metadata without introducing per-item tooltip overhead or network activity.
