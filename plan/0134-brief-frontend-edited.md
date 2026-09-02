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
* The hero lede's two clauses restate the fact cards and carry little signal: the
  regime clause ("conditions are unusually high") is really load — already shown in
  the load card — and is `ordinary` on 89% of days; the second clause is a chronic
  ~60-count of DAM constraints absent from the model, which never varies meaningfully
  and cannot be drilled into below.
* The Congested Region card is sign-blind: it derives from `abs(μ)` mass, so a zone
  whose congestion is *negative* (export/oversupply, prices below the system λ) reads
  the same as a scarcity zone, against the default "congestion = higher prices" read.
* The Brief topbar showed a redundant "DAM settled"/"forecast only" badge next to
  HeaderNav, and `an-brief-meta` printed run/horizon as bare unlabeled spans
  ("Run {id}", "final · t+1") instead of labeled fields like the Scoreboard
  topbar's `sb-meta` (label above/before a mono value).

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
* Rebuild the hero lede so it never restates the fact cards. Replace the load-regime
  clause and the unmodeled-constraint count with (a) an optional driver clause that
  ranks the peak-window (15–18 CT) wind/solar DAM-close forecasts or reports a settled
  load-vs-DAM miss, and (b) an always-present coverage clause (modeled ÷ all-DAM
  congestion) that reads "Awaiting DAM settlement" before settlement. Add the
  peak-window wind/solar reads and percentiles to `compute/analysis/hero_queries.py`.
* Carry the leading zone's signed congestion (`−(SF·μ)` mean by load zone) through
  `hero_builder._zone_summary` and `hero.classify_where` as `zone_congestion` (sign
  only; the magnitude is node-sampling sensitive). Regroup the region fact cards in
  `web/src/pages/BriefPage.tsx`: box 3 names the leading zone ("Congested Region"),
  and box 4 shows "{Region} μ Footprint" (share) and "{Region} Price" (above/below
  system) as two clean label/value pairs.
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
* Remove the "DAM settled"/"forecast only" badge from the Brief topbar (the
  `an-basis` span rendered beside `HeaderNav`). Reorganize `an-brief-meta` into
  labeled fields matching the Scoreboard topbar's `sb-meta` pattern (`label`
  class + mono value): "Model Run" → `provenance.run_id`; "Status" →
  `DAM Settled · t+1` when settled, `Forecast · t+{horizon}` otherwise.

## Acceptance

* [x] Primary navigation reads `Brief`, `Map`, `Matrix`, `Scoreboard` in that order.
* [~] Initial Brief load requests and renders all available Brief sections; settled
      days use grade/history and unsettled days retain a pending state without
      fabricated grade values. Remaining: exercise and record both states.
* [x] Brief → Map → Matrix → Brief changes the rendered route without a document
      reload, and returning to the same day reuses loaded Brief data rather than
      issuing duplicate requests.
* [x] The preferred reader-facing fact-card wording is retained: Total Congestion
      carries its median, the rank is labelled 30-Day Congestion, and the load
      card states actual versus forecast provenance.
* [x] Hero headlines now use capitalized, separate sentences without em-dash joins;
      direct LZ/HB benchmark splits provide a varied regional story ($/MWh spread),
      and DAM-only exceptions use plain language.
* [x] The lede is rebuilt as a driver clause (peak-window wind/solar rank, or a
      settled load-vs-DAM miss) plus an always-present coverage clause ("modeled
      constraints captured N% of system congestion"), reading "Awaiting DAM
      settlement" before settlement. It no longer restates the load card or the
      chronic unmodeled-constraint count. Verified on the regenerated 365-day audit:
      165 distinct ledes (from 82), longest identical run 3 days, driver fires on
      ~210/365 days (wind-light/strong, solar-strong, settled load miss).
* [x] The Congested Region stats are grouped across boxes 3–4 as clean label/value
      pairs: box 3 names the leading zone ("Congested Region" → South); box 4 shows
      "{Region} μ Footprint" (share %) and "{Region} Price" (above/below system).
      The price sign comes from the leading zone's signed nodal congestion
      (`−(SF·μ)` mean), surfaced as `where.zone_congestion`; a ±$1/MWh dead band
      leaves a flat zone unlabelled.
* [x] Both Watch prices CTA lines have consistent vertical spacing across desktop
      and mobile layouts.
* [x] Run and horizon provenance precede the integrated day control: a prominent
      CT date, availability-aware previous/next carets, and Load Window all use
      the cached URL update path.
* [~] The Docker Compose web production build (including TypeScript compilation)
      and focused hero tests pass. Focused hero tests pass (10/10, incl. the new
      driver/coverage lede and `zone_congestion` sign) and the checked-in
      hero_audit_365 fixture is regenerated against prod. Remaining: run the web
      production build (local Node 18 cannot build) and restart the API so the
      served slots include `zone_congestion`.
* [x] The Brief topbar no longer shows the standalone "DAM settled"/"forecast
      only" badge; `an-brief-meta` shows labeled "Model Run" and "Status" fields
      (Docker Compose web production build passes).
