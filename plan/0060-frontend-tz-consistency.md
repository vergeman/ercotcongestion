# 0060 - frontend-tz-consistency

Type: fix
Branch: fix/0060-frontend-tz-consistency

## Goal

* Pin all user-facing timestamps to Central (`America/Chicago`), labeled "CT".
* Interpret `datetime-local` picker input as CT when converting to the UTC wire format.
* Fix `PlaybackScrubber` cursor label that renders local time but claims "UTC".

## Context

* API/DB and wire format are already UTC (`_coerce_utc`, `toISOString()`). No backend change.
* `date-fns` `format()` uses browser-local. Scrubber's "UTC" suffix is a lie whenever the browser isn't on UTC; picker's `datetime-local` is interpreted as browser-local, not CT.
* Use `America/Chicago` (zone), not fixed CST, so DST is handled.

## Approach

Three commits.

### Commit 1 — chore: add tz helpers

* Add dep: `date-fns-tz`.
* New `web/src/lib/time.ts`: `ERCOT_TZ`, `formatCT`, `ctInputToUtc`, `utcToCTInputString`.

### Commit 2 — fix: scrubber displays CT

`web/src/components/playback/PlaybackScrubber.tsx`: cursor + slider-endpoint labels via `formatCT`; " CT" replaces the mislabeled " UTC".

### Commit 3 — feat: picker treats input as CT

`web/src/components/playback/DateRangePicker.tsx`: initial state / presets fill via `utcToCTInputString`; `handleCustomLoad` uses `ctInputToUtc`. Section + Start/End labels read "(CT)".

Do NOT touch: API code, `prefetch.ts`, curated-event ISO strings, or anything outside the picker/scrubber.

## Acceptance

* [x] Scrubber cursor + slider labels show CT wall-clock ending in " CT"; no "UTC" text in playback UI.
* [x] Picker labels read "(CT)"; input treated as CT on load, prefilled as CT on presets.
* [x] `tsc -b` clean.
* [ ] Dev-server smoke: pick a window, confirm outgoing `start`/`end` = CT-input converted to UTC; scrubber wall-clock matches CT.
* [ ] DST-straddling window renders contiguous CT wall-clock.
