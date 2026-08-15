# 0134 - brief-frontend-edited

Type: feat
Branch: feat/0134-brief-frontend-edited

## Goal

* Integrate BriefPage into the App's client-side Router so Brief, Map, and Matrix
  transitions re-render in place without a document reload or loss of loaded data.
* Clarify the Brief's hero, fact cards, links, and day-selection controls so every
  displayed metric and sentence is understandable and grammatically correct.
* Provide one integrated delivery-day control with previous/next navigation, a
  prominent CT date, and the existing Load Window action.

## Context

* BriefPage currently owns its fetch state outside the App shell; visiting Map and
  returning can unmount it and repeat the Brief requests instead of reusing data.
* HeaderNav currently lists Map, Matrix, Scoreboard, Brief, while the Brief date
  picker is isolated above the page content.
* The hero phrase book exposes ambiguous terms such as “weight” and “outside the
  model vocabulary,” uses an em dash, and can emit lower-case sentence starts.
* The second hero fact reports a 30-day rank and median dollar value without naming
  the congestion/shadow-price quantity being ranked.

## Approach

* Work in: `web/src/main.tsx`, `web/src/App.tsx`, `web/src/components/layout/HeaderNav.tsx`,
  `web/src/pages/BriefPage.tsx`, `web/src/components/playback/DateRangePicker.tsx`,
  and the smallest shared data/cache module or provider needed to retain Brief data.
  Update `compute/analysis/phrases.py` and its tests for server-generated hero copy.
* Entry point / primary change: make the Router/App shell own the Brief route and
  its persistent delivery-day data lifetime.
* Make App the routed shell for `/`, `/map`, and `/matrix`; keep Map/Matrix's shared
  explorer session intact, mount Brief through the Router, and route primary links
  with React Router rather than full-page navigation. Cache or lift Brief responses
  by delivery date/run so returning to an already loaded day re-renders existing
  data without duplicate fetches.
* Reorder `HeaderNav` to `Brief`, `Map`, `Matrix`, `Scoreboard`; preserve URL time
  coordinates and the existing Scoreboard behavior unless routing requires a
  narrowly scoped adjustment.
* On initial Brief load, request and render the complete available Brief surface:
  hero, standouts, top constraints, top nodes, context, and settled grade/history;
  retain honest settlement-pending states where grade data is unavailable.
* Rename the 30-day fact/detail to identify the ranked measure explicitly (the
  congestion/shadow-price total, Σμ, and its 30-day comparison population). Replace
  “weight” with an explicit description of the μ-weighted congestion footprint and
  replace “outside the model vocabulary” with plain language describing DAM
  constraints absent from the forecast artifact.
* Revise phrase templates and rendering so hero headlines and ledes start with
  capitalized words, use complete sentences instead of em-dash joins, and retain
  the underlying bucket/count facts. Keep the segmented API contract intact.
* Make the two lines of the “Watch prices” CTA use one consistent line-height and
  inline/block treatment; verify spacing both in the hero CTA and its inline mobile
  link.
* Replace the isolated Brief date-picker placement with a unified day control:
  prominent formatted CT date, accessible previous/next-day carets, and the Load
  Window action in one responsive group. Day changes must update the existing
  URL coordinate and use the same cached data path; do not add a second playback
  transport.
* Do NOT change grade calculations, Brief endpoint semantics, Map/Matrix data
  contracts, or the deliberate detail-panel behavior from `0135` after renumbering.

## Acceptance

* [x] Primary navigation reads `Brief`, `Map`, `Matrix`, `Scoreboard` in that order.
* [x] Initial Brief load renders all available Brief sections and issues the needed
      data requests; settled days show grade/history and unsettled days show pending
      state without fabricated grade values.
* [x] Brief → Map → Matrix → Brief changes the rendered route without a document
      reload, and returning to the same day reuses loaded Brief data rather than
      issuing duplicate requests.
* [~] The fact cards now use a consistent two-stat structure: Total Congestion
      carries its median; the rank is labelled 30-Day Congestion; and the load
      card states actual versus forecast provenance. Remaining: decide whether the
      final reader-facing wording must explicitly name Σμ and its comparison
      population.
* [ ] Hero headline and lede use capitalized sentence starts, contain no em-dash
      joins, and explain the measured conditions, μ-weighting, and DAM-only
      exceptions in plain language.
* [x] Both Watch prices CTA lines have consistent vertical spacing across desktop
      and mobile layouts.
* [~] Run and horizon provenance now precede the existing Load Window picker.
      Remaining: expose previous/next carets, make the CT date prominent, and
      combine them into one integrated day control that preserves the cached URL
      update path.
* [~] The web production build (including TypeScript compilation) passes. Remaining:
      run and record the focused hero/frontend tests for this plan.
