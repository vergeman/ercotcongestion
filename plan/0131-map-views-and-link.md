# 0131 - map views and link

Type: feat
Branch: feat/0131-map-views-and-link
Depends on: 0130-map-view-data-controls

## Goal

* Put an inline map in the hero that links into `/map` at the delivery day's window,
  opening the layman price view (Market × LMP, canonicalized to Forecast × LMP before
  settlement) and requesting one playback.
* Serialize 0130's map state as the Map URL contract:
  `view=forecast|market|compare|error` (exactly one view) and
  `data=congestion|lmp`; `autoPlay` requests one playback. `constraint` and `sp`
  remain the selected-element contract.

## Context

* The target link, in full:

  ```
/map?t=2026-08-02T13Z&ws=2026-08-02T13Z&we=2026-08-04T13Z
      &view=market&data=lmp&autoPlay=true
  ```

* `t`, `ws` and `we` already exist and are already written by `0010`. They remain the
  shared coordinate; the new parameters are Map-only state. The Brief emits the
  coordinate and only adds a selection for a deliberate Map action — it must not
  retain an incoming `sp` or `constraint`.
* 0130 builds every rendered (view, data) state, its availability rules, and
  the persisted-λ implied LMP. This plan only serializes/deserializes that state — do
  not start it before 0130 lands.
* The hero targets Market × LMP, not the model's own congestion quantity: the layman
  gold standard is watching price move through a day. Pre-settlement the Map
  canonicalizes to Forecast × LMP, where dollars still render via persisted λ, so the
  hero link logic stays dumb.
* `autoPlay` is new **behaviour**, not a durable preference. Something must start the
  transport on mount and then stop being sticky, or every subsequent navigation within
  the session replays.
* The audience argument is the reason this exists at all: a reader who has never heard
  of a shadow price will not read a ranked constraint table, but will watch prices
  move across a map. The hero text and this image are the entire product for that
  reader — everything below the hero is for the reader who already stayed.
* `0002` carries `cursor: {ws, we, t}` on the hero response, so the link's time half is
  handed over rather than derived in the frontend.

## Approach

* Work in: `web/src/lib/mapLinks.ts`, `web/src/App.tsx`,
  `web/src/workspaces/MapWorkspace.tsx`, and the hero component. Keep time parsing in
  `useTimeCursor`; do not add Map view state to its time API.
* Parse and serialize a typed Map state matching 0130's axes. Canonical params:
  `view=forecast|market|compare|error` and `data=congestion|lmp`.
  Missing/unknown values use the shipped default (Forecast × Congestion).
* Canonicalization mirrors 0130's button rules — the URL can never land a state the
  buttons cannot reach:
  * `view=error` forces `data=congestion`.
  * `view=market|compare|error` with no settled data in the window downgrades to
    `view=forecast`, `data` preserved.
* `constraint=<canonical constraint key>` and `sp=<settlement-point id>` are already
  the Map/Matrix selection parameters. Keep their existing precedence (`constraint`
  wins), validation, and unavailable-target fallback; do not invent a second selected
  element parameter. A Brief Map action adds exactly one of them.
* Query updates must patch, not rebuild, the search string: a Map selection preserves
  `t/run/span/ws/we`, `view`, and `data`; Map ↔ Matrix navigation preserves
  `constraint`/`sp` and the shared coordinate. Brief navigation carries only the
  shared coordinate, so Map/Matrix selection state does not leak into the Brief.
* **`autoPlay` fires once and clears itself.** Consume it on arrival, start the transport,
  then strip it from the URL so a back-navigation or an in-session route change does not
  replay. A sticky autoplay is the failure mode to design against.
* Treat the still frame as **part of the hero**, not a panel below it. It sits with the
  headline, above every table. The frame shows the same view the link opens (Market
  LMP once settled, implied-LMP forecast before).
* Keep the inline image cheap. A static frame of the day's peak hour is enough — the
  motion is the reward for clicking, and the hero must not wait on map data to paint.
* Honour reduced motion: if the reader has `prefers-reduced-motion`, do not autoplay on
  arrival.
* The Brief's detail-panel Map action consumes the existing selection contract and
  focuses the matching representation without changing its supplied coordinate.
* Do NOT touch: the scrubber's own behaviour, `useExplorerSession`, or the time params.

## Acceptance

* [x] The hero renders an inline map frame for the delivery day, above the tables.
      Ships as a large right-aligned banner (Texas outline as the geographic
      reference, node dots colored by the hour's LMP-ish value) behind the
      headline, with the "Watch prices move across the day →" CTA in the top
      corner (a plain inline link beside "Run …" below the mobile breakpoint,
      where the image itself doesn't render at all).
* [x] Clicking it lands on `/map` at that day's window with
      `view=market&data=lmp&autoPlay=true`; pre-settlement the Map canonicalizes this
      to Forecast × LMP without a broken view. `t` is the window start (not the
      peak-μ hour `cursor.t`), so autoplay covers the full day rather than
      landing mid-arc.
* [x] `view` and `data` are typed, read by the Map, and canonicalized as above;
      unknown/absent values fall back to Forecast × Congestion. Verified against
      the dev API (`tsc` clean, `/map?view=market&data=lmp` and other combinations
      load correctly).
* [x] `view=error&data=lmp` lands on the congestion error view. `canonicalizeMapViewState`
      forces `data: "congestion"` whenever `view === "error"`, matching 0130's own
      Error-locks-congestion rule; spot-checked against the dev server.
* [x] `autoPlay` does not survive a subsequent in-session navigation — verify by
      navigating away and back. Live-verified after fixing a real race: the view-sync
      effect's own downgrade push (no settled data yet → forecast) was dropping
      `autoPlay` before the transport could consume it; `withCoord` now carries it
      forward until the transport's own one-shot consume-and-strip fires.
* [x] `prefers-reduced-motion` suppresses autoplay. Implemented in `TimeTransport`
      (still consumes/strips the request either way, just skips starting playback) —
      verified by code review, not exercised live via devtools emulation this pass.
* [x] The hero paints without waiting on map data. Hero text renders synchronously
      from the already-fetched `hero` response; `HeroMapPreview` fetches
      independently and shows a skeleton until it resolves.
* [ ] A Brief detail-panel Map action carries a valid `constraint` or `sp` to the Map,
      where it is focused without losing the selected day/window or Map view/data.
      No detail panel exists yet — that's `0134-brief-detail-panel`, not built. The
      underlying contract it will consume is ready and already exercised by the
      Standouts/Top Constraints/Top Nodes row links (`elementMapHref`), which carry
      the day's coordinate plus a `constraint`/`sp` target at the default Forecast ×
      Congestion view, no `autoPlay`.
* [x] Map selection changes and Map ↔ Matrix navigation preserve their applicable
      selection, Map view/data, and shared coordinate; Brief navigation drops
      `sp` and `constraint`. `withCoord` (App.tsx) fills t/ws/we/span/run/view/data
      only where the incoming search doesn't already set them; Brief never reads or
      forwards `constraint`/`sp` from its own URL, so every Brief-issued link is a
      fresh, deliberate selection.
* [x] Invalid or absent `constraint`/`sp` safely fall back to the normal Map.
      Inherited from 0130's `targetUnavailable` handling, unmodified.
* [x] `tsc --noEmit -p web/tsconfig.app.json` clean.

## Task note

* Done: Standouts (constraint + node rows), Top Constraints, and Top Nodes now build
  their `/map` links via `elementMapHref` — the day's coordinate, a `constraint` or
  `sp` target, and the default Forecast × Congestion view. `autoPlay` stays exclusive
  to the hero's own CTA, matching "only where intended."
