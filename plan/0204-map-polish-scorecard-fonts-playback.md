# 0204 - map-polish-scorecard-fonts-playback

Type: fix
Branch: fix/0204-map-polish-scorecard-fonts-playback

## Goal

* Stop the Scorecard panel flashing on scrub / playback — update numbers in place, never unmount the section.
* Replace `--font-mono` (JetBrains Mono) with a less AI-coded monospace; ship a small shortlist to trial.
* Smooth playback: visually interpolate node colors between hourly frames instead of hard-cutting.
* Stop the playback scrubber stuttering (hangs on an hour, then lunges to catch up).

## Context

* Scorecard fetch (`MapWorkspace.tsx:238`) is keyed on `deliveryDay`; the panel is passed `null` whenever `scorecard.delivery_date !== deliveryDay` (`:981`). Crossing a day boundary blanks the whole `<section>` (`SidePanel.tsx:448`), then remounts it when the new fetch lands — that is the FOUT.
* JetBrains Mono is self-hosted via `web/scripts/fetch-fonts.py` → `web/src/fonts.css`, applied through the `--font-mono` token and every `.mono` class.
* `GridMap.tsx` colors nodes via maplibre `feature-state` `color`, recomputed per hour from `congestion`/`spp` (`:761`). Feature-state swaps are instantaneous, so hour-to-hour jumps look stitled.
* Playback stutter is main-thread saturation, not I/O (the window is fully prefetched). Each `setInterval` tick fires two heavy items: `useSharedExplorer` mirrors the cursor into the URL every frame (`:50`) — a router navigation → double re-render — and `dayStats` (`useExplorerSession.ts:136`) recomputes whole-day stats on every hour because it's keyed on `currentIndex`, though its value only changes per delivery day. When a tick runs long the fixed-cadence timer slips, so the scrubber hangs then bunches.

## Approach

* Work in: `web/src/workspaces/MapWorkspace.tsx`, `web/src/components/panels/SidePanel.tsx`, `web/src/fonts.css` (+ `web/scripts/fetch-fonts.py`, `web/src/index.css`), `web/src/components/map/GridMap.tsx`.

* **Fix 1 — Scorecard flash.**
  * Retain the last good scorecard: keep passing the previous value while a new day's fetch is in flight instead of nulling on `delivery_date` mismatch. Gate the section on "ever had data", and mark it stale (e.g. dim) rather than unmounting.
  * On scrub within a single day `deliveryDay` is unchanged — verify no other prop (fitMeta) is toggling the section; the flash must only ever be a numbers swap.
  * Do NOT change the abort logic — stale-day publishes must still be blocked.

* **Fix 2 — Font swap. Chosen: Roboto Mono** (neutral, grotesk-derived so it tonally matches the Inter `--font-sans`; sheds the JetBrains look). Bundle weights **400 + 500**, and use **500** as the data weight — Roboto Mono runs wide and light, so 400 alone reads thin on the dark ground.
  * Add Roboto Mono (400/500) to `fetch-fonts.py`, regenerate `fonts.css`, switch `--font-mono` in `index.css` to `'Roboto Mono', ui-monospace, 'SF Mono', monospace`. Keep the fallback stack.
  * Known trade-off (accept, don't fix): plain oval `0`, no dot/slash — fine for numbers, slightly less disambiguated for hex/IDs.
  * Also-rans considered: IBM Plex Mono, DM Mono, Space Mono, Martian Mono, Source Code Pro; Commit Mono (free, needs manual bundle).

* **Fix 3 — Playback interpolation.**
  * Have the playback loop emit a fractional position between frame `i` and `i+1` (rAF-driven) rather than snapping index.
  * In the coloring effect, blend the numeric metric (`congestion`/`spp`) between the two bracketing hours by that fraction before mapping to color, then push feature-state each tick. Color eases; geometry/selection untouched.
  * Respect `prefers-reduced-motion`: fall back to the current hard-cut.
  * Do NOT touch data fetching or the URL time coordinate — interpolation is display-only, between already-loaded frames.

* **Fix 4 — Playback stutter.** Cut the per-tick work so the timer keeps cadence.
  * Work in: `web/src/hooks/useSharedExplorer.tsx`, `web/src/hooks/useExplorerSession.ts`.
  * URL mirror: stop writing the URL on every playback frame. Debounce the index→URL `setCoord`, or only sync when playback pauses/stops — a step/scrub still updates the URL, continuous play doesn't. Keep the URL→index direction intact so shared links and page hops still restore the cursor.
  * `dayStats`: key the memo on the CT `deliveryDay` string, not `currentIndex`, so it recomputes once per day instead of every hour.
  * Leave the tween as-is for now; revisit only if stutter persists.
  * Do NOT change what the URL encodes or the landing-load precedence.

## Acceptance

* [x] Scrubbing across a day boundary and running playback shows the Scorecard numbers change with no panel unmount/reflow (visually: no blank-then-reappear). — confirmed; the fix was retain + drop the stale-dim, not the cache (cache removed).
* [x] Stale-day scores are never shown as current — abort still gates publishes.
* [x] `--font-mono` renders Roboto Mono (weights 400 + 500 bundled, 500 for data) across all `.mono` data; build passes; fallback stack intact.
* [x] During playback, node colors transition smoothly between hours; reduced-motion falls back to hard cuts.
* [x] No new per-frame network fetches introduced by interpolation.
* [~] Playback holds a steady cadence — no hang-then-catch-up; the URL still restores the cursor after pausing or on a shared link. — single-map views steady; compare view improved via rAF clock + 30fps tween throttle, pending final confirmation (two-map repaint at 1106 nodes is the ceiling).
* [x] `dayStats` recomputes on delivery-day change, not every hour.
