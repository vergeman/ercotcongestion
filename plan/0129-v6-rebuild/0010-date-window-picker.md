# 0129-0010 - date-window-picker

Type: feat
Branch: feat/0129-0010-date-window-picker
Depends on: `0009` — **released together**, see branch note below

## Goal

* Give the brief page a single-date picker, replacing what the scrubber did for day
  navigation.
* Write the shared time coordinate on selection so a hop to `/map` needs no translation.
* Reuse `DateRangePicker`'s dropdown and curated-events wiring rather than forking it.

## Context

* Ships with `0009`. Un-mounting the scrubber removes the page's only way to change day.
* `web/src/components/playback/DateRangePicker.tsx` is the `📅 Load Window` control:
  presets, CT start/end inputs via `ctInputToUtc` / `utcToCTInputString`, optional
  `events` / `onSelectEvent` / `activeEventId`, and an `inline` mode. Map uses it at
  `web/src/workspaces/MapWorkspace.tsx:1031`; it also reaches the scrubber through
  `ExplorerScrubber`.
* Curated events come from `web/src/lib/events.ts` — each carries `window_start`,
  `window_end` and `cursor_ts`, which is what `useExplorerSession.loadWindow(start, end,
  cursorTs)` consumes.
* `0128`'s constraint still holds: briefs exist only for `available_dates`, and the live
  window need not overlap. A cursor on a day with no brief is a valid empty state.

## Approach

* Work in: `web/src/components/playback/`, `web/src/pages/`
* Add a **single-date variant** of `DateRangePicker` — same dropdown, same events
  wiring, same CT input handling, one date instead of a start/end pair. Do not fork the
  file: Map still needs the range form. The relative presets ("Last 6h / 24h / 3d / 7d")
  are range concepts and do not appear in the single-date variant.
* Trigger is a `📅 Load Date` button **on the brief page, above the hero** — explicitly
  not in `HeaderNav`, which stays a pure navigation + coordinate carrier.
* **Selection writes all three params**: `?t` to that day's peak hour, `?ws`/`?we` to
  that day's America/Chicago bounds. The window then matches what the reader is reading
  about, and `0011`'s deep link is correct without constructing anything at link time.
* **Reading is one-way**: day shown = the CT day of `?t`. Arriving from the Map with a
  week-wide window works — the day comes off `?t` and `?ws`/`?we` are left alone until
  the reader picks a date.
* Curated events pass through unchanged: selecting one sets the day from `cursor_ts`'s CT
  day and hands the full window through as-is.
* A selected day with no brief renders the empty state. **Do not silently snap the
  selection** to a nearby day that happens to have data — that hides the gap and makes
  the URL lie.
* Do NOT touch: the range form's behaviour on Map, `useExplorerSession`, or `HeaderNav`.

## Acceptance

* [x] `📅 Load Date` renders above the hero on the brief page and nowhere in `HeaderNav`.
* [x] Picking a date updates `?t`, `?ws` and `?we` together; the day shown matches the CT day of `?t`.
* [x] Map's Load Window is unchanged — same presets, same range behaviour, same events.
* [x] Selecting a curated event sets the day and passes its full window through.
* [x] A date with no brief shows the empty state and the URL keeps that date.
* [x] Brief → `/map` lands on the selected day's window with no further translation.
* [x] `tsc --noEmit -p web/tsconfig.app.json` clean.
