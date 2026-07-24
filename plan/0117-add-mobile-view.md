# 0117 - add-mobile-view

Type: feat
Branch: feat/0117-add-mobile-view

## Goal

* Deliver a map-first mobile layout that keeps the forecast-error map usable on phone-sized viewports.
* Replace desktop-only hover and floating-popover interactions with explicit tap selection and a mobile detail sheet.
* Preserve access to playback, network statistics, and ranked constraints without showing the desktop side panel or dual-map comparison.

## Context

* The current map console is a fixed desktop viewport: header controls, a two-pane comparison mode, a right side panel, bottom scrubber, floating legend, and hover-driven detail cards compete for limited mobile space.
* Mobile users have no durable hover state, so transient node/constraint previews and tooltip-only information are not reliable interactions.
* The existing forecast-error view is already the appropriate single-map landing view; the existing `SidePanel`, `PlaybackScrubber`, `DetailCard`, map selection callbacks, and constraint reach data should be reused where possible.
* This work is a responsive presentation and interaction adaptation; it must not change map API contracts, forecast calculations, or the desktop map workflow.

## Approach

### Commit 1: `feat(web): establish map-first mobile shell`

* Work in: `web/src/App.tsx`, `web/src/components/layout/Header.tsx`, `web/src/components/layout/HeaderNav.tsx`, `web/src/components/map/CompareMap.tsx`, `web/src/index.css`
* Entry point / primary change: responsive app layout and header controls.
* Define a shared mobile breakpoint (target: `768px`) and responsive layout classes/tokens rather than adding viewport checks throughout the component tree.
* At the mobile breakpoint, render only the forecast-error single-map experience. Do not offer the dual comparison control or mount the second synchronized map.
* Reduce the mobile header to product identity, connection state, theme toggle, and a button that opens the information drawer; hide desktop nav and desktop map-control groups that cannot fit without wrapping.
* Keep the active view, palette, overlay, and desktop header behavior unchanged at and above the breakpoint.
* Ensure the map fills the available viewport between the compact header and playback controls, respects safe-area insets, and does not cause document-level scrolling.
* Do NOT touch: API routes, API response types, map data transformations, or desktop visual layout outside responsive rules.

### Commit 2: `feat(web): add mobile playback and information drawer`

* Work in: `web/src/App.tsx`, `web/src/components/playback/PlaybackScrubber.tsx`, `web/src/components/playback/DateRangePicker.tsx`, `web/src/components/panels/SidePanel.tsx`, `web/src/index.css`
* Entry point / primary change: mobile-only drawer state and compact playback controls.
* Add an accessible mobile information drawer, controlled from the header, with a close control, focus management, Escape handling, and a backdrop that closes the drawer.
* Reuse the existing `SidePanel` tabs in that drawer so Stats and Constraints remain available without duplicating their data fetching or selection wiring.
* Move the date-range/event picker into the mobile drawer; keep it in the scrubber's left column on desktop.
* Restyle the mobile `PlaybackScrubber` as a fixed-height bottom control bar with previous, play/pause, next, current timestamp, and a large touch-friendly range input. Hide the sparkline and range endpoint labels on small screens.
* Keep all playback keyboard behavior and desktop scrubber controls intact.
* Do NOT touch: scoreboard page layout or the existing stats/constraint data and ranking behavior.

### Commit 3: `feat(web): make map inspection tap-only on mobile`

* Work in: `web/src/App.tsx`, `web/src/components/map/GridMap.tsx`, `web/src/components/map/DetailCard.tsx`, `web/src/components/map/Legend.tsx`, `web/src/components/panels/ConstraintPanel.tsx`, `web/src/components/ui/Tooltip.tsx`, `web/src/index.css`
* Entry point / primary change: map selection semantics and mobile bottom-sheet detail presentation.
* On mobile, disable hover-driven node cards, constraint previews, member-node hover rings, and map-marker hover isolation. Keep desktop hover behavior unchanged.
* Make a node tap pin and open its details; make a constraint marker or constraint-list tap select the constraint, show its reach/isolation on the map, and open its detail state. A blank-map tap clears the current selection and closes the sheet.
* Render the selected node or constraint detail as a bottom sheet on mobile, with a clear close action, a compact initial height, scrollable content, and an expanded state for full details. Preserve the existing floating `DetailCard` behavior on desktop.
* Replace tooltip-only mobile controls and descriptions with visible short labels or explicit information controls inside the drawer/sheet; suppress hover tooltip triggers on touch-sized viewports.
* Collapse the map legend to an explicit, tappable compact control on mobile; it must not obscure node taps when closed.
* Maintain selected-node rings and selected-constraint map styling as persistent selection feedback, not transient hover feedback.
* Do NOT touch: map reach/exposure endpoint contracts, desktop pointer interactions, or underlying chart/color calculations.

### Commit 4: `test(web): cover responsive interaction boundaries`

* Work in: `web/src/**/__tests__/` or the repository's established frontend test location, `web/package.json`, and any existing browser-test configuration if present.
* Entry point / primary change: mobile rendering and selection regression coverage.
* Add component/integration coverage for the mobile breakpoint: dual view is unavailable, drawer opens and closes accessibly, date/event selection is reachable in the drawer, and playback controls remain operable.
* Cover tap selection and clearing for nodes and constraints, including the guarantee that hover-only callbacks do not open a mobile detail sheet.
* Run the frontend lint and production build. Run the existing API tests only as a regression check if the project test workflow already includes them.
* Do NOT introduce a new end-to-end test framework solely for this feature.

## Acceptance

* [ ] At viewport widths below the defined breakpoint, the map page presents one forecast-error map, a compact header, and a touch-friendly playback bar; dual comparison is not available.
* [ ] Stats, Constraints, the date/event picker, and overlay controls are reachable through an accessible mobile drawer without obscuring the map by default.
* [ ] Tapping a node or constraint creates persistent selected feedback and opens its mobile detail sheet; hover-only behavior and floating popovers do not appear on mobile.
* [ ] Tapping empty map space clears the active selection and closes the detail sheet; desktop selection, hover, sidebar, and dual-map behavior continue to work unchanged.
* [ ] The mobile layout is usable at 320px-wide and 768px-wide viewports, respects safe-area insets, and has no unintended horizontal or document-level vertical scrolling.
* [ ] Frontend lint and production build pass.
