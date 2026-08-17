# 0135 - brief detail panel

Type: feat
Branch: feat/0135-brief-detail-panel
Depends on: `0129-0009`

## Goal

* Add one shared sliding detail panel for Standouts and selectable Top Constraints / Top
  Nodal Congestion rows.
* Let a reader orient the selected element on a small abstract map, inspect the evidence
  behind the row, then deliberately open the full Map from the panel sidebar.

## Context

* A Brief table row is an inspection action, not a direct navigation link. Direct links
  make the reader leave the brief before they understand why an item ranked.
* The full interactive Map remains `/map`. The panel map is deliberately small and
  abstract: geolocation/footprint for orientation, not a second Map workspace or a
  second playback transport.
* `0129-0009` owns mode detection and every main-page forecast-only/post-settle rendering
  decision. This plan only consumes that already-selected mode to avoid showing
  unavailable evidence in a detail panel. Map views and their deeplink contract are
  separately deferred to `0130-map-views-and-link`.
* This plan needs a second pass before implementation: decide the expanded panel
  contents and the honest location/footprint contract for nodes and constraints.

## Approach

* Work in: `web/src/pages/`, `web/src/components/`, `web/src/api/`; extend serving
  endpoints only where row detail or coordinates are not already present.
* Define a discriminated selection model for `standout`, `constraint`, and `node`.
  Preserve stable identity, delivery-day coordinate, and mode when a row opens the
  panel. Do not duplicate display strings as keys.
* The panel is a right-side sliding overlay with a backdrop and accessible dialog
  semantics. It opens from a row click and keyboard activation, returns focus to its
  trigger when closed, and closes through close control, Escape, and backdrop click.
  Opening/closing never rewrites `?t`, `?ws`, or `?we`.
* Consume the rendering mode selected by `0129-0009` for detail copy and evidence visibility.
  Do not introduce a second settled-availability test or a second mode decision here.
* Render a lightweight abstract map/footprint from server-provided location data. It
  must paint independently of the full Map's frame fetch and explain unavailable
  coordinates without inventing a location.
* Leave the existing Brief `/map` links unchanged. A later pass can add a panel-owned
  Map action after `0130-map-views-and-link` defines the supported target state.
* Do NOT mount `ExplorerLayout`, `ExplorerScrubber`, or MapWorkspace inside the panel.

## Acceptance

* [ ] Each Standout and selectable row in both ranked tables opens the same detail panel;
      none is a direct navigation link.
* [ ] The panel has correct keyboard behavior, dialog semantics, focus return, close
      control, Escape close, and backdrop close.
* [ ] Opening and closing it leaves the Brief URL time coordinate unchanged.
* [ ] The panel consumes 0009's selected mode and never makes a second availability
      decision or renders unavailable settled evidence.
* [ ] The abstract map is geolocated when data exists, remains lightweight, and has an
      honest unavailable-location state.
* [ ] Existing Brief `/map` links are unchanged; a Map handoff is not an acceptance
      condition until `0130-map-views-and-link` is defined.
* [ ] `tsc --noEmit -p web/tsconfig.app.json` clean.
