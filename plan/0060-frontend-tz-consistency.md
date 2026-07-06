# 0060 - frontend-tz-consistency

Type: fix
Branch: fix/0060-frontend-tz-consistency

## Goal

* Pin all user-facing timestamps to Central Time (`America/Chicago`), labeled "CT".
* Interpret `datetime-local` picker input as CT (not browser-local) when converting to the UTC wire format.
* Fix `PlaybackScrubber` cursor label that renders local time but claims "UTC".

## Context

* `DateRangePicker` uses `<input type="datetime-local">` + `new Date(str)` — treats input as browser-local, not CT. `format(...)` for presets also fills the input in browser-local.
* `PlaybackScrubber.tsx:94` renders `format(current, "MMM d, yyyy HH:mm") + " UTC"` — `date-fns format()` uses local time, so the "UTC" suffix is a lie whenever the browser isn't on UTC.
* API/DB layer is already UTC end-to-end (`_coerce_utc`, `toISOString()` on the wire). No backend change needed.
* ERCOT operates on Central; users think in CT. DST must be handled — use zone `America/Chicago`, not a fixed CST offset.

## Approach

Three commits on the branch:

### Commit 1 — chore: add tz helpers

* Add dep: `date-fns-tz`.
* New file `web/src/lib/time.ts` exporting:
  * `export const ERCOT_TZ = "America/Chicago";`
  * `formatCT(d: Date, fmt: string): string` — wraps `formatInTimeZone`.
  * `ctInputToUtc(local: string): Date` — wraps `fromZonedTime(local, ERCOT_TZ)` for `datetime-local` strings.
  * `utcToCTInputString(d: Date): string` — `formatInTimeZone(d, ERCOT_TZ, "yyyy-MM-dd'T'HH:mm")` for prefilling the input.
* No call-site changes yet.

### Commit 2 — fix: scrubber displays CT, not mislabeled UTC

Work in: `web/src/components/playback/PlaybackScrubber.tsx`.

* Replace `format(current, "MMM d, yyyy HH:mm") + " UTC"` → `formatCT(current, "MMM d, yyyy HH:mm") + " CT"`.
* Replace both slider-endpoint `format(...)` calls with `formatCT(...)` and append " CT" to the right-hand label (or both, whichever reads cleaner).

### Commit 3 — feat: picker treats input as CT

Work in: `web/src/components/playback/DateRangePicker.tsx`.

* Presets and initial state: fill `startStr` / `endStr` via `utcToCTInputString(d)` instead of `format(d, "yyyy-MM-dd'T'HH:mm")`.
* `handleCustomLoad`: `onLoad(ctInputToUtc(startStr), ctInputToUtc(endStr))` instead of `new Date(...)`.
* Add a `(CT)` hint next to the Start / End labels so the user sees which zone the input represents.

Do NOT touch: API code, `_coerce_utc`, `prefetch.ts` cache keys, curated-event ISO strings (already UTC on the wire), or any component outside the picker/scrubber.

## Acceptance

* [ ] Scrubber cursor and slider-endpoint labels show CT wall-clock and end in " CT". No "UTC" text in the playback UI.
* [ ] Typing `2025-01-03T10:00` in the picker (from any browser timezone) sends `start=2025-01-03T16:00:00Z` to the API (CT → UTC).
* [ ] DST boundary: a window that straddles the spring-forward or fall-back day still displays contiguous CT wall-clock and returns correct UTC-anchored data.
* [ ] Presets ("Last 24h", etc.) prefill the picker with CT wall-clock strings; loading a preset from a non-CT browser still queries the correct absolute window.
* [ ] `git grep -n '" UTC"' web/src` returns no user-facing label matches.
