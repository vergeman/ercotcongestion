# 0106 - web-legend-detailcard-polish

Type: fix
Branch: fix/0106-web-legend-detailcard-polish

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Rebuild the map `Legend` so the gradient stays inside its container, the type/range copy is legible, and the redundant bottom title is gone (all three views).
* Add breathing room between the pane-subtitle stat chips (`nodes` / `forecast` / `priced`).
* Make the `DetailCard` a two-way constraint↔node explorer: hover a driver row to isolate its constraint on the map, hover a member node to ring it, and click either to load it into the card — the same synced-hover contract the `ConstraintPanel` already uses.
* Brighten the light-mode constraint-overlay colors (GTC, transmission corridors) so the light map reads as clearly as dark.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* Post-#157 styling review found the `Legend` (`web/src/components/map/Legend.tsx`) illegible: gradient bar bleeds past the container edges on every view, the congestion `Window |max| · anchor = |value| P90` sub-line and the `Shape = type · size ∝ binding hours` sub are too small to read, and the `paneLabel` at the card bottom just repeats the pane subtitle drawn on the map.
* The `DetailCard` (`web/src/components/map/DetailCard.tsx`) already routes a driver-row *click* to `handleConstraintClick`, but has no hover isolation and no way to walk back from a constraint's member nodes into a node card — capability the `ConstraintPanel` (plan/0103) already ships via `onHover` / `onMemberHover` / `onSelect`. The map wiring (`handleConstraintHover`, `setHoveredMemberSp`, `handleSpClickPrediction`) already exists in `App.tsx`; the card just isn't wired to it.
* Light-mode `--sf-*` tokens (`index.css`) were darkened for white-ground contrast (4.9–7.1:1 as *text*), but as map fills they read dull/muddy — the mustard-brown GTC (`#a16207`) and deep-purple transmission (`#6d28d9`) especially — versus the vivid dark-mode set.
* Open decision (1c): the congestion legend's color anchor is P90 (`mcStats.p_high` / `max_abs`), while the `DetailCard` reports `Forecast (P50)`. Simplifying the sub-line to a plain min/max range is copy-only; re-anchoring the *color scale* to P50 would change `lib/colors.ts` normalization and the map itself — treat as a separate decision, do NOT fold it into the copy fix.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. Grouped into natural commits. -->

### Commit A — `fix(web): legend legibility and containment` (item 1)

* Work in: `web/src/components/map/Legend.tsx`; touch `web/src/App.tsx` only for the two `signLabels` strings (line ~938) and to drop the now-unused `paneLabel` prop from the three `<Legend>` call sites.
* Entry point: the `Legend` component + its inline `<style>` block (`BAR_W`, `.legend`, `.legend__bar`).
* **1a/1d/1g — size + containment:** widen the legend (raise `BAR_W` and the `.legend` `width`, which is `BAR_W + 20`) so the title fits on one line and the copy uncramps. Fix the bleed: the `.legend__bar` / `.legend__hist` are set to a fixed `BAR_W` while `.legend` has `8px 10px` padding — constrain the bar to the padded content box (e.g. `width: 100%` inside a content wrapper, or reduce bar width to `BAR_W - 2*pad`) so the gradient endpoints never overrun the rounded container. Verify on congestion, LMP, and forecast-error bars.
* **1b/1e — remove the bottom title:** stop rendering the `paneLabel` block (`.legend__pane-label`) — it duplicates the on-map pane subtitle. Remove the `paneLabel` prop from `Props` and all three call sites in `App.tsx`.
* **1c — simplify the congestion sub-line:** replace `Window |max| {max_abs} · anchor = |value| P90` (`.legend__sub`, lines ~214-216) with a concise min/max range readout only (drop the words "Window" and "anchor = |value| P90"). Copy-only — do NOT change `mcStats`/`lib/colors.ts` normalization (see the P50 decision in Context).
* **1e — forecast-error cleanup:** in the `overviewTypes` block, remove the `Shape = type · size ∝ binding hours · hover a node…` sub entirely (lines ~269-271). The type marks stay; only the explanatory sub goes.
* **1f — concise diverging labels:** the forecast-error view passes `signLabels={{ neg: "Under-forecast", pos: "Over-forecast" }}` (App line ~938). Shorten to fit the widened container (e.g. `Under` / `Over`, or `Under-fcst` / `Over-fcst`) and confirm they don't wrap.
* Do NOT touch: `lib/colors.ts`, the LMP histogram logic, or the `mcStats` anchoring.

### Commit B — `fix(web): pad pane-subtitle stat chips` (item 2)

* Work in: `web/src/App.tsx`, the inline `.pane-badge__meta` rule (line ~1018).
* Increase the `gap` between the `nodes` / `forecast` (and `nodes` / `priced` / `compared`) stat chips from `10px` to a larger value so the two counts read as distinct. If the title↔meta spacing also reads tight, bump `.pane-badge` `gap` (currently `1px`) too.
* Do NOT touch: the badge tooltip strings or the `badgeFor` logic.

### Commit C — `feat(web): two-way constraint↔node hover/click in DetailCard` (item 3)

* Work in: `web/src/components/map/DetailCard.tsx` (add hover/click props + handlers) and `web/src/App.tsx` (wire them at the three prediction/error-pane `<DetailCard>` call sites, lines ~840, ~945).
* Entry point: `ExposuresBody` (driver rows) and `ReachBody` (member-node rows).
* **New `DetailCard` props:** `onHoverConstraint?(id: string | null)`, `onHoverMember?(sp: string | null)`, `onSelectMember?(sp: string)`. Keep the existing `onSelectConstraint` (click a driver → constraint reach).
* **ExposuresBody (constraint drivers):** add `onMouseEnter`/`onMouseLeave` to each `.dc-driver` button that fire `onHoverConstraint(e.constraint_key)` / `onHoverConstraint(null)`. Click already calls `onSelectConstraint` — keep it. Net: hover isolates the constraint on the map; click opens that constraint's `ReachBody` card.
* **ReachBody (member nodes):** the member rows are currently `.dc-driver--static` (no interaction). Make each row fire `onHoverMember(s.settlement_point)` on enter / `onHoverMember(null)` on the list's leave (ring the node on the map), and turn the row into a button that calls `onSelectMember(s.settlement_point)` on click (load that node's card). Drop `--static` where these handlers are wired.
* **App wiring:** pass `onHoverConstraint={handleConstraintHover}` and `onHoverMember={setHoveredMemberSp}` (both already exist and drive `isolatedConstraint`/`ringedSpId` on the prediction & error `GridMap`s). For `onSelectMember`, reuse `handleSpClickPrediction(spId, props)` — resolve the SP's feature props (`sp_type`, `load_zone`) by looking the `settlement_point` up in `spPoints.features` so the pinned card body populates; a member click leaves reach mode (that handler already `setReach(null)`s).
* Result: from a pinned node card → hover/click a driver constraint → its member nodes → hover/click a member back into a node card, ping-ponging constraint↔node, matching the `ConstraintPanel` behavior.
* Do NOT touch: the actual-pane `<DetailCard>` (line ~880, `showDrivers={false}`) — it stays realized-only; do NOT re-fetch reach in the card (App owns `fetchMapReach`).

### Commit D — `fix(web): brighten light-mode constraint colors` (item 3-colors)

* Work in: `web/src/index.css`, the `:root[data-theme='light']` block `--sf-*` tokens (lines ~156-160).
* Raise the chroma/lightness of `--sf-gtc` (mustard-brown `#a16207`) and `--sf-transmission` (deep-purple `#6d28d9`) toward their vivid dark-mode hues so the overlay fills read bright on the white ground, while keeping the type hues mutually distinct (the CVD ΔE 47+ separation noted in `Legend.tsx`). Re-check `--sf-radial` for the same dullness.
* These tokens are *categorical fills* on the map (not body text), so the strict 4.5:1 text-contrast constraint that forced the dark set does not apply — the earlier comment reasons about them as text. Keep them readable against `--map-*` grounds; brightness/chroma is the lever, verify against both the overlay marks and the `Legend` type key.
* Do NOT touch: the dark `:root` `--sf-*` set, or the diverging data palettes in `lib/colors.ts` (those deliberately do not flip with theme).

### Commit E - `fix(web): remove loading FOUTs on PlaybackScrubber and ConstraintPanel`

* `PlaybackScrubber.tsx`: show empty PlaybackScrubber on load.
* `ConstraintPanel.tsx`: move loading to left of button to avoid vertical shift.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] A — Legend gradient bar sits fully inside the container (no endpoint bleed) on congestion, LMP, and forecast-error views.
* [x] A — Legend title renders on a single line; congestion sub-line shows a plain min/max range with no "Window"/"anchor"/"P90" text.
* [x] A — No bottom `paneLabel` title on any legend; forecast-error legend has no `Shape = type · size` sub; `Under`/`Over` labels fit without wrapping.
* [x] B — Visible gap between the `nodes` and `forecast`/`priced`/`compared` stat chips on all three pane subtitles.
* [x] C — Hovering a driver-constraint row in the `DetailCard` isolates that constraint on the map; hovering a member node rings it; clicking a driver opens its constraint card and clicking a member opens that node's card — round-trip works both directions.
* [x] C — The actual (ERCOT) pane's `DetailCard` is unchanged (no drivers, no member interaction).
* [x] D — On the light-mode map the GTC and transmission overlay fills read bright/vivid (comparable to dark mode), and the three type hues remain distinguishable.
* [x] `npm run build` (or the CI build) passes; note the local Node-18 build limitation ([[web-type-system]]) — verify types compile in the CI-parity environment.
